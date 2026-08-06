"""
agents/report_agent.py
Claude APIを呼び出して解釈付き週次レポートを生成するエージェント
"""

import json
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import anthropic

logger = logging.getLogger(__name__)

SKILL_REFS_DIR = Path(__file__).parent.parent / "skills" / "jpx-investor-data" / "references"

# 使用モデルは .env / GitHub Secrets の CLAUDE_MODEL で切替可能。
# 2026-07-27 A/B比較（7/17週）の結果 Opus 5 へ移行。フォールバックも Opus 5 に揃える
# （以前は Sonnet 4.6 で、CLAUDE_MODEL 未設定のローカル実行が黙って別モデルになっていた）。
DEFAULT_MODEL = "claude-opus-5"

# Opus 5 は thinking 未指定でも適応思考が有効になり、思考トークンが max_tokens 枠を消費する。
# 実測では思考オフでも16,384枠の82%を使ったため上限を引き上げる。
# 16k超の非ストリーミングはSDKのHTTPタイムアウトに当たるため streaming が必須。
MAX_TOKENS = 32000
THINKING = {"type": "adaptive"}


def _get_model() -> str:
    return os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)

INVESTOR_JP = {
    "foreign":    "海外投資家",
    "individual": "個人投資家",
    "trust_bank": "信託銀行",
    "inv_trust":  "投資信託",
    "corporate":  "事業法人",
    "dealer":     "自己（証券会社）",
}


def _load_reference(filename: str) -> str:
    """知識ファイルを読み込む"""
    path = SKILL_REFS_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"[{filename} が見つかりません]"


# 週次・月次レポート共通の表現規律。ネット集計データから確認できないことを
# 断定させないためのガードレール（外部AI査読 2026-07-04 の指摘を反映）。
EXPRESSION_DISCIPLINE = """## 【重要】表現の規律（データから確認できないことを断定しない）

本データは投資部門別のネット集計値である。以下を厳守すること：

- **相対取引の相手方**: ネット集計から取引の相手方は特定できない。
  「カウンターパーティ」「〜の反対側」「〜の買いを受ける形」「受け皿」等と断定せず、
  「集計上、Aの買い越しに対しBが売り越し」とのみ表現する。
- **異種商品の枚数の合算・規模比較の禁止（表・本文とも）**: 乗数・原資産が異なる商品をまたぐ枚数合計
  （例:「先物合計 -39,781枚」）は参考値としても記載しない。
  さらに**ラージ換算・標準換算した後であっても、日経225とTOPIXの枚数を「どちらが大きいか」の
  規模比較に使ってはならない**（例:「TOPIXは8,689.2枚で日経225の2,826.5枚の約3倍」は禁止）。
  指数水準も1枚あたりの契約金額も異なるため、枚数比は経済規模の比にならない。
  **原資産をまたぐ規模比較は実約定金額ネット（億円）だけで行う**。
  ラージ換算/標準換算は「同一原資産内でラージとミニを統合する」ためだけに使う値である。
  商品別の説明は生枚数、同一原資産内の総合方向はラージ換算/標準換算、
  原資産をまたぐ総合規模・優劣は実約定金額ネットで表現する。
- **投資家の内訳・意図の断定禁止**:
  - 信託銀行をGPIFと同一視しない。「GPIF等の年金リバランスを含む可能性がある信託銀行フロー」等と表現する。
  - 海外投資家をCTA・マクロHFと断定しない（ロングオンリー・パッシブ・ETF等も含まれる）。
  - 投資信託の買い越しを「設定増」「ニューマネー流入」と断定しない（解約減・リバランス等と区別できない）。
  - 「保険付き」「本格的ポジション縮小」「一過性ではない」「リアルマネー主導」等、
    フローの目的・性質・運用属性は断定しない。
    オプションデータには新規/手仕舞い・限月・行使価格・建玉増減が無いため、
    確認できるのは「現物・先物の売り越しとプット買い越しが同時に観測された」まで。
  - **新規/手仕舞いの断定禁止**: ネットの増減から「ショートカバー」「新規売り」「買い戻し」
    「プレミアム獲得狙い」等を断定しない（「〜の可能性」まで）。
- **自己（証券会社）**: MM・顧客フローの反対売買・在庫ヘッジ等を含み、方向性ポジションと解釈しない
  （「自己=MM」と完全同義にもしない）。現物・先物の符号が一致しても両輪買い/両輪売りとは呼ばず、
  「現物・先物とも買い越し（ただしMM・在庫等のフロー）」と表現する。
- **GEX判定はProxy**: 本データには行使価格・限月・建玉が無い。「-GEX環境」と断定せず、
  「契約枚数ベースでは-GEXバイアスを示すProxy判定」のように推定であることを明記する。
  判定の基本は**自己のコール＋プット合計（標準換算）のネット方向**とし、内訳を併記する。
  コール/プットや標準/miniで方向が割れる場合は「混在」と評価する。
- **統計閾値の規律**: 使用してよい数値基準は|Z|=2.0（異常水準への出入り）のみ。
  Z=-3、「▼2兆円」、「-1以上へ回復」等、それ以外の数値閾値・反転条件を発明しない。
  反転確認の条件は「縮小」「転換」「拡大」「異常水準（|Z|≧2）から通常範囲へ回復」等の
  相対表現で書く（例:「Zが-2以下から通常範囲へ回復」は可、「-1以上へ回復」は不可）。
  Zスコア単独で「売られすぎ」「買われすぎ」「平均回帰」「セリングクライマックス」「底打ち」を
  判定しない（確認できるのは「週次フローが統計的異常水準」まで）。
  「追撃売り」等の週内の執行行動を示す語も週次ネット額からは導かない。
  Zスコアに言及する際は必ず対象を明記する（例:「現物52週Z」「先物52週Z」）。
- **規模表現の根拠**: 「大規模」「極端」「全面的」等の形容にはZスコア・前週比・金額等の根拠を添える。
- **俗語・感情的表現の禁止**: 「養分」等の俗語を使わない。
- **必須条件の断定回避**: 「真の転換には〜が必要」と断定せず、「〜は有力な確認材料の一つ」と表現する。
- **戦略名の断定回避**: 組成（同一限月・行使価格・同時性）が確認できないため、
  「ベア・コンビネーション」等の戦略名で確定させず「コール売り＋プット買いの弱気方向フロー」
  「〜型の方向性を示すフロー」と表現する。
- **NT（日経225 vs TOPIX）方向の判定**: NT倍率＝日経225÷TOPIX。したがってTOPIX優位は
  NT倍率の**低下**方向であり、「NTロング」ではない。以下を厳守する。
  - 「NTロング」「NTショート」の語は、**日経225とTOPIXのネット金額の符号が逆のときだけ**使ってよい。
    日経225買い越し・TOPIX売り越し → NTロング方向。日経225売り越し・TOPIX買い越し → NTショート方向。
  - **両方買い越し／両方売り越しはスプレッド取引ではない**。「両指数とも買い越しで、
    金額ではTOPIX側が大きい（TOPIX優位）」のように、符号が同方向である事実と規模の優劣だけを述べる。
    TOPIX優位の両建て買いを「NTロング型フロー」と書くのは方向が逆であり、結論を反転させる重大な誤りとなる。
    相対バイアスに触れる場合も「NT倍率低下方向のバイアスを示唆し得るが、両指数とも買い越しのため
    純粋なNTショート取引とは確認できない」と留保を必ず添える。
  - 符号が逆の場合も、同一主体による純粋なNTスプレッド取引かはネット集計から確認できないため、
    「〜方向の組み合わせ（純粋なスプレッド取引かは確認不能）」と書く。
  - 判定はデータ末尾の「NT方向（機械判定による事実）」ブロックの分類のみを根拠とし、推測で書き換えない。
    NTの優劣判定は金額で行い、ラージ換算枚数の大小をNT方向の根拠にしない。
- **スタイル・セクター解釈**: 「グロース売り・バリュー選好」「セクターローテーション」は
  業種別データが無い限り「可能性」に留める。
- **オプション戦略の優劣**: IV水準・スキュー・残存日数の情報が無いため、
  特定戦略を「優位」と断定せず「検討候補」に留める。ネイキッド売り回避等のリスク警告は可。
- **方向性乖離の明示**: 現物と先物の符号が逆の投資家は、合算の符号にかかわらず
  判定欄・本文で「方向性乖離（現物売り・先物買い等）」を明記する。
- **SQ日程の事実**: 日経225のSQは毎月**第2金曜**、メジャーSQは3・6・9・12月の第2金曜。
  「第3金曜のSQ」とは書かない（第3金曜は米国の満期・FTSEリバランス等であり、言及するなら別イベントとして分離する）。
- **行動・意図語の追加禁止**: 「買い戻し」「選好」「追随売り」「ヘッジ姿勢の裏付け」等、
  取引の目的・執行行動を示す語をネット集計から使わない。オプションと現物先物の関係は
  「下方向バイアスのフローとして整合」のように「整合」で表現する。
  現物Zと先物Zの水準差は「統計的異常度に差がある」と記述し、CTA等の主体名で説明しない（可能性表現でも不可）。
- **信託銀行の評価語**: 「リバランスまたはヘッジ調整と整合し得る」まで。
  「機械的リバランス・バイ」と断定せず、「暴落底」「歴史的規模」等の価格・規模描写を根拠なしに使わない。
- **事業法人と自社株買い**: 直接結び付けない。本文・チェックリストとも「現物の買い支えの有無」
  「売り越しの縮小/買い越し転換」で書き、自社株買いの実行状況は「企業開示で別途確認」と添える。
- **Proxy GEXの混在明記**: 日経225オプション計net（標準換算）が一方向でも、標準/miniやコール/プットで
  方向が割れる場合は「-GEXバイアスを伴う混在環境」のように混在を明記する。
- **Proxy判定に基づく戦略の条件付き表現**: 「順張り優位が定石」等と断定せず、
  「建玉・IV・日経VI等でも確認された場合に値動き増幅リスクを高く評価」のような条件付きで書く。
  逆張りは全面禁止ではなく「確認前はポジションサイズを抑える」と表現する。
- **単位の明記**: 先物の総合規模は必ず金額（億円）で表記する（「先物合計▼」のような単位なし表現は不可）。
- **Scheduled Flow（予定された機械的フロー）の区別**: ETF分配金捻出売り・ETF設定/解約・
  配当再投資・SQ/MSQロール・指数リバランス（MSCI/FTSE/日経225/TOPIX入替）・
  月末/四半期末リバランス・自社株買い・大型公募/売出し等の「予定された機械的フロー」が
  対象期間に存在し得る場合、投資主体のネット売買を投資家の方向性判断・リスク選好・
  恒常的な資金流出入と同一視しない。ネット集計からは機械的フローと方向性売買を分解できないため、
  「〜が一部含まれる可能性」までに留め、売買の全額を特定イベントに帰属させない。
  イベントの事前推計額（グロス）とJPXネット値を機械的に差し引いた「調整後ネット」を作らない。
- **オプションフローと取引目的の分離（3段階）**: 確認できるのは①フローの向きと規模
  （コール/プットの買い越し・売り越し）まで。②「下方向の保護需要または弱気方向のフローを示唆」は解釈。
  ③「既存ロングのヘッジ」「新規の弱気ポジション」「スプレッドの一部」「手仕舞い」の別は、
  限月・行使価格・新規/転売区分・建玉増減が無いため**確認不能**。
  「プット買い越し＝下方ヘッジ姿勢」「ヘッジを行った」「保険を掛けている」と目的で断定せず、
  「プットを買い越した。下方向の保護または弱気方向のフローを示唆するが、目的は確認不能」と書く。
  エグゼクティブサマリーでも同じ規律を適用し、「ヘッジ姿勢」を確定事実として要約しない。
- **オプションは原資産別に集計・表示する**: 標準換算（標準＋mini÷10）は日経225オプション専用の換算。
  表題は必ず「日経225オプション標準換算net」と原資産を明記する。
  TOPIXオプション・JPX日経400オプションは原資産・乗数が異なるため、同じ表・同じ合計に混ぜず
  別項目として扱う。「日経225・TOPIX・JPX400 合計」のような見出し・数値を作らない。
- **自己部門とMMを同一視しない（見出しも含む）**: 「自己（MM）のガンマ・ポジション」のような
  見出し・小見出しを使わない。「自己部門を用いたProxy GEX判定」と書き、
  自己部門にはMMのほか在庫・顧客注文の反対売買等が含まれること、
  週間フローは建玉在庫ではないことを本文に明記する。
- **規模の区分語の根拠**: 「ノイズ」「小〜中」「大」「超大」等の区分語を使う場合は、
  参照知識の「需給規模の量的感覚スケール」に基づく**本レポート規定の区分**であることを明記する
  （例:「本レポート規定の区分では『大』（±3,000〜10,000億円）に相当」）。
  根拠を示さずに「大ゾーン」「異例の規模」「歴史的」と書かない。区分を示せない場合は
  「4,921.6億円の売り越し」のように数値だけを記載する。
- **唯一性の範囲限定**: 本データの対象は6主体のみで全投資部門を網羅していない。
  「唯一の主体」と断定せず「表示対象6主体の中で唯一」と範囲を明示する。
- **資金管理ルールは分析の結論ではない**: 「1トレードの許容損失は総資金の2%以内」等は
  参照知識に置かれた一般的な運用ルールであり、今回のJPXデータから導かれた結論ではない。
  記載する場合は「別途定めた資金管理ルール」と明示する。口座資金・損切り幅・ボラティリティの
  入力が無いため、具体的な建玉枚数・投入金額は算出しない。
- **参照知識と本規律の優先順位**: 後述の「参照知識」は解釈フレームワークであり、
  そのままの断定文言（「ディーラーは〜する」「-GEXでは徹底した順張り」「CTAが売った」
  「2%ルール」等）を本文へ転記してはならない。参照知識と本規律が食い違う場合は**本規律を優先**し、
  参照知識の記述は必ず本規律の留保表現（Proxy判定・可能性・条件付き）に落として使う。
- **事実区分の意識**: 各記述が「データから確認できる事実」「入力値から再計算した値」「解釈」
  「確認不能」のどれに当たるかを書き手として区別する。解釈には「示唆」「可能性」を付け、
  確認不能な事項をエグゼクティブサマリーの断定文に混ぜない。
- **丸め注記**: 数値テーブル群の最後に
  「※表示値は丸めのため、表示値同士の再計算と0.1〜1億円程度の差が生じる場合がある」を1行入れる。
"""


def _second_friday(year: int, month: int) -> date:
    """指定月の第2金曜（日経225オプション・先物のSQ算出日）を返す。"""
    first = date(year, month, 1)
    offset = (4 - first.weekday()) % 7  # 月曜=0 … 金曜=4
    return first + timedelta(days=offset + 7)


def _build_sq_facts(week_date: date) -> str:
    """対象週・翌週のSQ日該当を機械計算した事実ブロックを返す（週次レポート用）。

    生成AIが「対象週」と「翌週」のSQ該当を推測で書き分けて誤る事故
    （対象週がSQ週なのに「来週のSQ週に留意」と書く等）を防ぐ。
    """
    week_start = week_date - timedelta(days=4)
    next_start = week_date + timedelta(days=3)
    next_end   = week_date + timedelta(days=7)

    def _sq_in(start: date, end: date) -> date | None:
        for y, m in {(start.year, start.month), (end.year, end.month)}:
            sq = _second_friday(y, m)
            if start <= sq <= end:
                return sq
        return None

    def _label(sq: date | None) -> str:
        if sq is None:
            return "SQ日を含まない"
        kind = "メジャーSQ" if sq.month in (3, 6, 9, 12) else "通常SQ"
        return f"{sq.strftime('%m月%d日')}（第2金曜）が{kind}算出日"

    return f"""
## SQ日程（機械計算による事実。これ以外のSQ日を推測で書かないこと）

- 対象週（{week_start.strftime('%m/%d')}〜{week_date.strftime('%m/%d')}）: {_label(_sq_in(week_start, week_date))}
- 翌週（{next_start.strftime('%m/%d')}〜{next_end.strftime('%m/%d')}）: {_label(_sq_in(next_start, next_end))}

対象週にSQ日が含まれる場合、SQは「対象週内に通過済みのイベント」として振り返りで扱うこと。
翌週にSQ日が無いのに「来週はSQ週の水曜に留意」等と翌週の警戒事項に書いてはならない。
"""


# ── 時間軸（レポート作成日時と対象期間の整合） ─────────────────────
# JPXの公表遅延・祝日ずれ・手動再生成により、対象週から見た「翌週」が
# レポート作成時点では既に経過していることがある。経過済みの週を
# 「来週の注目点」として書くと時制が破綻するため、機械判定して見出しを固定する。
# （2026-08-06 外部査読: 8/6作成のレポートが 8/03〜8/07 を「来週」と表記した指摘）
JST = timezone(timedelta(hours=9))
TSE_CLOSE = time(15, 30)  # 東証の大引け。これ以降ならその日は「経過済み」とみなす


def classify_period(as_of: date, period_start: date, period_end: date) -> str:
    """対象期間が作成日から見て PAST / IN_PROGRESS / FUTURE のどれかを返す。"""
    if period_end < as_of:
        return "PAST"
    if period_start <= as_of <= period_end:
        return "IN_PROGRESS"
    return "FUTURE"


_PERIOD_HEADINGS = {
    "PAST":        "対象週の翌週（{s}〜{e}）の事後検証項目",
    "IN_PROGRESS": "進行中の週（{s}〜{e}）の残存監視項目",
    "FUTURE":      "次週（{s}〜{e}）の注目点",
}
_PERIOD_NOTES = {
    "PAST":        "作成時点で既に終了した週である。「来週」「今後の警戒事項」としては書かない。",
    "IN_PROGRESS": "作成時点で進行中の週である。「来週」とは書かない。経過済みの日と未経過の日を分けて書く。",
    "FUTURE":      "作成時点で未到来の週である。「次週の注目点」「今後の監視項目」として書いてよい。",
}


def _build_time_axis_facts(week_date: date, as_of: datetime) -> str:
    """レポート作成日時と対象週・翌週の時制関係を機械判定した事実ブロックを返す。"""
    as_of_date = as_of.date()
    week_start = week_date - timedelta(days=4)
    next_start = week_date + timedelta(days=3)
    next_end   = week_date + timedelta(days=7)

    state = classify_period(as_of_date, next_start, next_end)
    fmt = {"s": next_start.strftime("%m/%d"), "e": next_end.strftime("%m/%d")}

    lines = [
        "",
        "## 時間軸（機械判定による事実。これ以外の時制表現をしないこと）",
        "",
        f"- レポート作成日時: {as_of.strftime('%Y年%m月%d日 %H:%M')} JST",
        f"- 対象週: {week_start.strftime('%m/%d')}〜{week_date.strftime('%m/%d')}（集計対象。既に終了）",
        f"- 対象週の翌週: {next_start.strftime('%m/%d')}〜{next_end.strftime('%m/%d')} → 判定: {state}",
        f"- この期間に使ってよい見出し: 「{_PERIOD_HEADINGS[state].format(**fmt)}」",
        f"- {_PERIOD_NOTES[state]}",
    ]

    if state != "FUTURE":
        last_done = as_of_date if as_of.time() >= TSE_CLOSE else as_of_date - timedelta(days=1)
        done_end = min(last_done, next_end)
        if done_end >= next_start:
            lines.append(
                f"- 経過済み: {next_start.strftime('%m/%d')}〜{done_end.strftime('%m/%d')}"
                "（東京市場は引け後。事後検証の対象であり、今後の警戒事項として書かない）"
            )
        if done_end < next_end:
            remain_start = max(done_end + timedelta(days=1), next_start)
            lines.append(
                f"- 未経過: {remain_start.strftime('%m/%d')}〜{next_end.strftime('%m/%d')}"
                "（監視対象として書いてよい）"
            )
        lines.append(
            "- 禁止: この期間を「来週」と表記すること、既に経過した日を「今後の注目点」に含めること。"
        )
    lines.append("")
    return "\n".join(lines)


def _last_weekday_of_month(d: date) -> date:
    """d が属する月の最終平日（月〜金）を返す。祝日は考慮しない。"""
    import calendar
    last = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
    while last.weekday() > 4:  # 土=5, 日=6
        last -= timedelta(days=1)
    return last


def _build_calendar_facts(week_date: date) -> str:
    """月末・四半期末の該当を機械判定した事実ブロックを返す。

    「月末である」ことはConfirmedだが、「月末リバランスが実行された」「その寄与額」は
    ネット集計から分解できないため Unconfirmed として扱わせる。
    """
    week_start = week_date - timedelta(days=4)
    month_end = _last_weekday_of_month(week_date)
    has_month_end = week_start <= month_end <= week_date
    is_quarter_end = has_month_end and month_end.month in (3, 6, 9, 12)

    hit = (f"{month_end.strftime('%m月%d日')}（月末最終平日・暦ベース）を含む"
           if has_month_end else "含まない")
    return f"""
## カレンダー事実（機械計算。該当＝確認できる事実、フローの発生・寄与額＝確認不能）

- 対象週（{week_start.strftime('%m/%d')}〜{week_date.strftime('%m/%d')}）に月末最終平日: {hit}
- 四半期末（3/6/9/12月末）: {"該当" if is_quarter_end else "非該当"}

「月末である」ことは確認できる事実だが、「月末リバランスが実行された」「その寄与額」は
投資部門別ネット集計から分解できないため確認不能として扱うこと。
月末であることを根拠に売り越し・買い越しの原因を断定しない。
"""


# ── 年次Scheduled Flowカレンダー ──────────────────────────────────
# 国内株ETF（日経225・TOPIX連動の主要ETF）の決算日は例年7月8日・10日に集中し、
# 分配金捻出のための大規模な換金売り（現物・先物）が決算週とその前後に発生する。
# 2026年は約1.5兆円規模の売り需要が事前推計された（2026-07-16生成レポートの
# 外部査読で「投信売り越し-1.05兆円の解釈にこのScheduled Flowが欠落」と指摘）。
_ETF_DIST_START = (7, 8)   # 決算集中日（開始）
_ETF_DIST_END   = (7, 10)  # 決算集中日（終了）

_ETF_DIST_NOTE_MAIN = """
## 【Scheduled Flow】国内株ETFの決算・分配金捻出売り（毎年7月上旬の年次イベント）

対象週は、国内株ETF（日経225・TOPIX連動の主要ETF）の決算日（例年7月8日・10日に集中）に
近接している。ETFは分配金支払いの原資を捻出するため、決算日前後に大規模な換金売り
（現物・先物）を機械的に執行する。売りは決算日当日に集中せず事前に分散執行されることが
あるため、決算日を含む週やその前週の週次データに現れ得る。以下を厳守すること：

- 投資信託（場合により信託銀行・自己の一部）の売り越しには、投資家の方向性判断ではなく
  ETF分配金捻出を目的としたScheduled Flow（予定された機械的フロー）が相当程度含まれている
  可能性がある。この可能性を、エグゼクティブサマリーと投資信託セクションの両方で、
  売り越しの方向性解釈より先に明記する。
- JPXの投資主体別ネット集計からは、分配金捻出売り・設定/解約・通常のリバランス・
  方向性売買を分解できない。「一部含まれる可能性が高い」までは記載できるが、
  「売り越しの全額がETF換金売り」とは断定しない。市場の事前推計額（グロス）と
  ネット集計値を機械的に差し引いた「調整後」の数値も作らない。
- 投資信託の大幅売り越しを「恒常的な資金流出」「継続的な弱気判断」「翌週以降も継続する
  方向性売り」と断定しない。Zスコアの異常水準は事実として記載してよいが、
  Scheduled Flowの可能性を必ず併記する。
- 「国内勢の異常な売り 対 海外勢の強気買い」のような二項対立を過度に強調しない。
  「予定された機械的供給を海外投資家の買いが吸収した可能性がある週」等の表現に留める
  （ネット集計から相手方は特定できないため断定しない）。
- 戦略示唆・反転確認チェックリストに「ETF分配金イベント通過後に投資信託の売り越しが
  縮小するか」を含める。イベント通過後も大幅売り越しが継続した場合に初めて、
  方向性の資金流出の可能性を引き上げて評価する。
"""

_ETF_DIST_NOTE_POST = """
## 【Scheduled Flow】国内株ETF決算・分配金イベントの通過確認（毎年7月上旬の年次イベント）

対象週は、国内株ETF（日経225・TOPIX連動の主要ETF）の決算日（例年7月8日・10日に集中）の
直後に当たる。直前の週までの投資信託等の大幅売り越しには、ETF分配金捻出のための機械的な
換金売り（Scheduled Flow）が含まれていた可能性がある。

- イベント通過後に投資信託の売り越しが縮小したかを必ず評価する。縮小していれば
  「直前の売りに機械的フローが含まれていた可能性と整合」、通過後も大幅売り越しが
  継続していれば「方向性の資金流出の可能性を引き上げ」と段階的に評価する（断定はしない）。
"""

# 年次カレンダー（7月上旬のETF分配金）に該当しない週は、Scheduled Flow の
# イベント入力が無い状態である。無入力を「イベント無し」と読み替えて季節性を
# 事実のように書くことを防ぐため、確認不能の定型文を明示的に渡す。
_SCHEDULED_FLOW_NO_INPUT = """
## 【Scheduled Flow】イベントカレンダー未入力（確認不能事項として明記すること）

本レポートには Scheduled Flow（予定された機械的フロー）のイベント入力が与えられていない。
したがって、ETF分配金捻出売り・ETF設定/解約・配当再投資・指数リバランス（MSCI/FTSE/日経225/TOPIX入替）・
月末/四半期末リバランス・自社株買い・大型公募等が投資主体別数値に与えた影響は**確認不能**である。

- 「Scheduled Flowカレンダーが入力されていないため、ETF分配金捻出売り・指数リバランス・
  配当再投資等が投資主体別数値に与えた影響は確認不能」と一度明記すること。
- 「月初の新規資金流入」「欧米勢の夏季休暇による流動性低下」等の一般的な季節性仮説は、
  今回の入力からは確認できない。記載する場合は「一般的な季節性仮説であり今回の数値からは
  確認不能」と明示し、確認された数値と混ぜて断定しない。
- 特定のイベントを、ある主体の売り越し・買い越しの原因として断定しない。
"""


def _build_scheduled_flow_note(week_date: date) -> str:
    """対象週が年次Scheduled Flowイベント（7月上旬のETF分配金捻出売り）に
    近接する場合の注意ブロックを返す。該当しない週は空文字列。"""
    week_start = week_date - timedelta(days=4)
    etf_start = date(week_date.year, *_ETF_DIST_START)
    etf_end   = date(week_date.year, *_ETF_DIST_END)

    in_event_week = week_start <= etf_end and week_date >= etf_start
    pre_window  = week_date < etf_start and (etf_start - week_date).days <= 14
    post_window = week_start > etf_end and (week_start - etf_end).days <= 14

    if in_event_week or pre_window:
        return _ETF_DIST_NOTE_MAIN
    if post_window:
        return _ETF_DIST_NOTE_POST
    return _SCHEDULED_FLOW_NO_INPUT


def _fmt_net(val: float | None) -> str:
    """AI に渡すデータテーブル用: 符号付き数値（正=買い越し、負=売り越し）。
    ▲/▼ は会計上「マイナス」を意味する用法もあり AI が誤読しやすいため使用しない。
    """
    if val is None:
        return "-"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:,.1f}億円"


def _fmt_diff(val: float | None) -> str:
    if val is None:
        return "-"
    return f"{'+' if val >= 0 else ''}{val:,.1f}"


def _log_cache_usage(message, label: str = "") -> None:
    """Anthropic API レスポンスの usage から cache hit/miss をログ出力する。

    cache_creation_input_tokens: キャッシュ書き込み（初回）
    cache_read_input_tokens:     キャッシュヒット（2回目以降）
    """
    usage = getattr(message, "usage", None)
    if usage is None:
        return
    created = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read    = getattr(usage, "cache_read_input_tokens", 0) or 0
    in_tok  = getattr(usage, "input_tokens", 0) or 0
    out_tok = getattr(usage, "output_tokens", 0) or 0
    tag = f"[{label}] " if label else ""
    if read > 0:
        logger.info(f"{tag}[Cache HIT] read={read:,}tok, input={in_tok:,}tok, output={out_tok:,}tok")
    elif created > 0:
        logger.info(f"{tag}[Cache CREATE] created={created:,}tok, input={in_tok:,}tok, output={out_tok:,}tok")
    else:
        logger.info(f"{tag}[Cache MISS] input={in_tok:,}tok, output={out_tok:,}tok")


FUTURES_TYPE_JP = {
    "nikkei225_large": "日経225ラージ",
    "nikkei225_mini":  "日経225ミニ",
    "topix_large":     "TOPIXラージ",
    "topix_mini":      "TOPIXミニ",
}
FUTURES_TYPE_ORDER = ["nikkei225_large", "nikkei225_mini", "topix_large", "topix_mini"]
BREAKDOWN_INVESTORS = ["foreign", "trust_bank", "individual", "inv_trust", "corporate", "dealer"]
BREAKDOWN_LABELS = {
    "foreign":    "海外投資家",
    "trust_bank": "信託銀行",
    "individual": "個人",
    "inv_trust":  "投資信託",
    "corporate":  "事業法人",
    "dealer":     "自己",
}

# オプションは投資信託(inv_trust)カラムがDBに無い場合があるため、
# 投資家コード対応の "investment_trust" にもフォールバック
OPTION_TYPE_JP = {
    "nikkei225_call":      "日経225 コール",
    "nikkei225_put":       "日経225 プット",
    "nikkei225_mini_call": "日経225mini コール",
    "nikkei225_mini_put":  "日経225mini プット",
    "topix_call":          "TOPIX コール",
    "topix_put":           "TOPIX プット",
    "jpx400_call":         "JPX400 コール",
    "jpx400_put":          "JPX400 プット",
}
OPTION_TYPE_ORDER = [
    "nikkei225_call", "nikkei225_put",
    "nikkei225_mini_call", "nikkei225_mini_put",
    "topix_call", "topix_put",
    "jpx400_call", "jpx400_put",
]
# オプションパーサで使われる投資家キー (parse_options_csv.INVESTOR_CODES と一致)
OPTION_INVESTORS = ["foreign", "trust_bank", "individual", "investment_trust", "corporate", "dealer"]
OPTION_INVESTOR_JP = {
    "foreign":          "海外投資家",
    "trust_bank":       "信託銀行",
    "individual":       "個人",
    "investment_trust": "投資信託",
    "corporate":        "事業法人",
    "dealer":           "自己",
}


def _build_options_table(options_rows: list[dict]) -> str:
    """オプション売買データから AI プロンプト用テキストを生成。

    投資家×コール/プット×標準/ミニ のクロス集計
    """
    if not options_rows:
        return "=== オプション売買データなし ==="

    # {investor: {option_type: {net_lots, net_oku}}}
    from collections import defaultdict
    data: dict = defaultdict(lambda: defaultdict(lambda: {"net_lots": 0, "net_oku": 0.0}))
    for r in options_rows:
        inv = r.get("investor_type", "")
        ot  = r.get("option_type", "")
        data[inv][ot]["net_lots"] += r.get("net_lots", 0) or 0
        data[inv][ot]["net_oku"]  += r.get("net_amount_oku", 0.0) or 0.0

    lines = [
        "=== 株価指数オプション 投資家別 売買差引（原資産別。net、正=買い越し / 負=売り越し）===",
        "  表記: 枚数 / 億円 (プレミアム金額換算、負=プレミアム支払超過、正=プレミアム受取超過)",
        "  ※日経225 / TOPIX / JPX400 は原資産・乗数が異なる。合算せず原資産別に評価すること。",
        "",
    ]
    # ヘッダー
    col_w = 22
    header = f"{'投資家':<14}" + "".join(f"{OPTION_TYPE_JP[ot]:>{col_w}}" for ot in OPTION_TYPE_ORDER)
    lines.append(header)
    lines.append("-" * (14 + col_w * len(OPTION_TYPE_ORDER)))

    for inv in OPTION_INVESTORS:
        if inv not in data:
            continue
        row_label = OPTION_INVESTOR_JP.get(inv, inv)
        cells = []
        for ot in OPTION_TYPE_ORDER:
            d = data[inv].get(ot, {"net_lots": 0, "net_oku": 0.0})
            cells.append(f"{d['net_lots']:+,}枚/{d['net_oku']:+.1f}億")
        line = f"{row_label:<14}" + "".join(f"{c:>{col_w}}" for c in cells)
        lines.append(line)

    # 標準換算枚数（miniは乗数が標準の1/10のため、生枚数の単純合算は経済量として無意味）
    def _std_eq(inv: str, kind: str) -> float:
        return (
            (data[inv].get(f"nikkei225_{kind}", {}).get("net_lots", 0) or 0)
            + (data[inv].get(f"nikkei225_mini_{kind}", {}).get("net_lots", 0) or 0) / 10
        )

    lines.append("")
    lines.append("--- 日経225オプション 標準換算枚数（= 日経225標準 + 日経225mini÷10）---")
    lines.append("  ※これは日経225オプション専用の換算。TOPIX・JPX400オプションは原資産・乗数が")
    lines.append("    異なるため、この換算・この合計に含めない（別項目として扱うこと）。")
    lines.append("  ※日経225オプション内での規模の比較・合算は必ずこの値で行うこと。")
    for inv in OPTION_INVESTORS:
        if inv not in data:
            continue
        c_std, p_std = _std_eq(inv, "call"), _std_eq(inv, "put")
        lines.append(
            f"  {OPTION_INVESTOR_JP.get(inv, inv):<10}: "
            f"コール net {c_std:+,.1f}枚 / プット net {p_std:+,.1f}枚 / "
            f"日経225オプション計 net {c_std + p_std:+,.1f}枚"
        )

    if "foreign" in data:
        fp_std = _std_eq("foreign", "put")
        fc_std = _std_eq("foreign", "call")
        lines.append("")
        lines.append(
            f"※ 海外投資家の日経225オプション（標準換算）: "
            f"プット net {fp_std:+,.1f}枚、コール net {fc_std:+,.1f}枚。"
        )
        lines.append(
            "   確認できるのは向きと規模まで。プット買い越し優位は下方向の保護需要または"
            "弱気方向のフローを示唆するが、"
        )
        lines.append(
            "   既存ロングのヘッジ／新規の弱気ポジション／スプレッドの一部／手仕舞いの別は"
            "限月・行使価格・建玉増減が無いため確認不能。"
        )

    return "\n".join(lines)


def _build_futures_breakdown(futures_rows: list[dict]) -> str:
    """先物内訳テーブル（商品種別×投資家）を生成"""
    from collections import defaultdict

    data: dict = defaultdict(lambda: defaultdict(lambda: {"net_lots": 0, "net_oku": 0.0}))
    for r in futures_rows:
        ft  = r.get("futures_type", "")
        inv = r.get("investor_type", "")
        data[ft][inv]["net_lots"] += r.get("net_lots", 0) or 0
        data[ft][inv]["net_oku"]  += r.get("net_amount_oku", 0.0) or 0.0

    col_w = 18
    lines = [
        "=== 先物内訳（商品種別×投資家）枚数 / 億円 ===",
        "  ※金額はJPX公表の実約定金額。明細セルは億円に丸めて表示しており、",
        "    丸め前の値で計算する合計と±1億円程度ずれることがある。",
        "  ※枚数はラージ/ミニで乗数が、日経/TOPIXで原資産が異なるため、",
        "    商品をまたぐ生枚数の合算は経済的に無意味。合計は金額のみ。",
        "  ※「ラージ換算」行（= ラージ + ミニ÷10）は同一原資産内でラージとミニを統合するための値。",
        "    日経225とTOPIXは原資産・指数水準・1枚あたりの契約金額が異なるため、ラージ換算同士でも",
        "    合算してはならず、「どちらが大きいか」の規模比較にも使ってはならない。",
        "    原資産をまたぐ規模比較・優劣判定は実約定金額ネット（億円）のみで行うこと。",
        "",
    ]
    header = f"{'商品':<18}" + "".join(f" {BREAKDOWN_LABELS[i]:>{col_w}}" for i in BREAKDOWN_INVESTORS)
    lines.append(header)
    lines.append("-" * (18 + (col_w + 1) * len(BREAKDOWN_INVESTORS)))

    for ft in FUTURES_TYPE_ORDER:
        if ft not in data:
            continue
        row = f"{FUTURES_TYPE_JP.get(ft, ft):<18}"
        for inv in BREAKDOWN_INVESTORS:
            d = data[ft][inv]
            cell = f"{d['net_lots']:+,}枚/{d['net_oku']:+.0f}億"
            row += f" {cell:>{col_w}}"
        lines.append(row)

    # ラージ換算枚数（= ラージ + ミニ÷10）。原資産が異なる日経とTOPIXは合算しない
    conv_specs = [
        ("日経225ラージ換算", "nikkei225_large", "nikkei225_mini"),
        ("TOPIXラージ換算",  "topix_large",     "topix_mini"),
    ]
    for label, lg, mn in conv_specs:
        row = f"{label:<18}"
        for inv in BREAKDOWN_INVESTORS:
            v = (
                (data.get(lg, {}).get(inv, {}).get("net_lots", 0) or 0)
                + (data.get(mn, {}).get(inv, {}).get("net_lots", 0) or 0) / 10
            )
            cell = f"{v:+,.1f}枚"
            row += f" {cell:>{col_w}}"
        lines.append(row)

    lines.append("-" * (18 + (col_w + 1) * len(BREAKDOWN_INVESTORS)))
    totals_oku: dict = defaultdict(float)
    for ft in data:
        for inv in BREAKDOWN_INVESTORS:
            totals_oku[inv] += data[ft][inv]["net_oku"]
    total_row = f"{'金額合計（全商品）':<18}"
    for inv in BREAKDOWN_INVESTORS:
        cell = f"{totals_oku[inv]:+,.1f}億"
        total_row += f" {cell:>{col_w}}"
    lines.append(total_row)

    return "\n".join(lines)


# ── NT方向（日経225 vs TOPIX）の機械判定 ──────────────────────────
# NT倍率 = 日経225 ÷ TOPIX。TOPIX優位はNT倍率の「低下」方向であり NTロングではない。
# 生成AIが「TOPIXを強く買い越す＝NTロング」と逆方向に書く事故を防ぐため、
# 分類をPython側で確定させてデータに埋め込む。
# （2026-08-06 外部査読で「結論を反転させる最大の問題」と指摘された箇所）
def classify_nt_bias(nikkei_net_amount: float, topix_net_amount: float) -> dict:
    """日経225先物とTOPIX先物のネット金額（億円・正=買い越し）からNT方向を分類する。

    枚数ではなく金額で判定する（原資産が異なるため枚数の大小は経済規模の大小ではない）。
    """
    n, t = nikkei_net_amount, topix_net_amount
    if n > 0 and t < 0:
        return {
            "classification": "NT_LONG_CANDIDATE",
            "label": "日経225買い越し・TOPIX売り越し → NTロング方向の組み合わせ",
            "note": "同一主体による純粋なNTスプレッド取引かはネット集計から確認不能",
        }
    if n < 0 and t > 0:
        return {
            "classification": "NT_SHORT_CANDIDATE",
            "label": "日経225売り越し・TOPIX買い越し → NTショート方向の組み合わせ（NT倍率低下方向）",
            "note": "同一主体による純粋なNTスプレッド取引かはネット集計から確認不能",
        }
    if n > 0 and t > 0:
        leader = "TOPIX優位" if t > n else ("日経225優位" if n > t else "同程度")
        return {
            "classification": "BOTH_BUY",
            "label": f"両指数とも買い越し（金額ベースで{leader}）",
            "note": "スプレッド取引ではない。NTロング/NTショートの語を使わない",
        }
    if n < 0 and t < 0:
        leader = ("TOPIX側の売りが優位" if abs(t) > abs(n)
                  else ("日経225側の売りが優位" if abs(n) > abs(t) else "同程度"))
        return {
            "classification": "BOTH_SELL",
            "label": f"両指数とも売り越し（金額ベースで{leader}）",
            "note": "スプレッド取引ではない。NTロング/NTショートの語を使わない",
        }
    return {
        "classification": "ONE_SIDE_ZERO_OR_NEUTRAL",
        "label": "片側が中立（ゼロ）",
        "note": "NTロング/NTショートの語を使わない。方向は指数ごとに個別に記載する",
    }


def nt_amounts_by_investor(futures_rows: list[dict]) -> dict:
    """投資家別に日経225先物・TOPIX先物のネット金額（億円）を合算して返す。"""
    from collections import defaultdict

    amt: dict = defaultdict(lambda: {"nikkei": 0.0, "topix": 0.0})
    for r in futures_rows:
        ft  = r.get("futures_type", "")
        inv = r.get("investor_type", "")
        oku = r.get("net_amount_oku", 0.0) or 0.0
        if ft.startswith("nikkei225"):
            amt[inv]["nikkei"] += oku
        elif ft.startswith("topix"):
            amt[inv]["topix"] += oku
    return dict(amt)


def _build_nt_bias_facts(futures_rows: list[dict]) -> str:
    """投資家別のNT方向分類（機械判定）をテキストブロックとして返す。"""
    amt = nt_amounts_by_investor(futures_rows)

    lines = [
        "=== NT方向（機械判定による事実。この分類以外のNT表現をしないこと）===",
        "  NT倍率 = 日経225 ÷ TOPIX。判定は実約定金額ネット（億円）で行う（枚数では判定しない）。",
        "  「NTロング」「NTショート」は日経225とTOPIXの符号が逆のときだけ使用可。",
        "  両方買い越し／両方売り越しはスプレッド取引ではないため、規模の優劣のみを述べること。",
        "",
    ]
    for inv in BREAKDOWN_INVESTORS:
        if inv not in amt:
            continue
        n, t = amt[inv]["nikkei"], amt[inv]["topix"]
        c = classify_nt_bias(n, t)
        lines.append(
            f"  {BREAKDOWN_LABELS.get(inv, inv):<6}: "
            f"日経225 {n:+,.1f}億円 / TOPIX {t:+,.1f}億円 → {c['label']}"
        )
        lines.append(f"          ※{c['note']}")
    return "\n".join(lines)


def _build_spot_futures_detail(context: dict, futures_rows: list[dict]) -> str:
    """海外投資家・信託銀行の現物・先物クロス詳細を生成"""
    from collections import defaultdict

    data: dict = defaultdict(lambda: defaultdict(lambda: {"net_lots": 0, "net_oku": 0.0}))
    for r in futures_rows:
        ft  = r.get("futures_type", "")
        inv = r.get("investor_type", "")
        data[ft][inv]["net_lots"] += r.get("net_lots", 0) or 0
        data[ft][inv]["net_oku"]  += r.get("net_amount_oku", 0.0) or 0.0

    inv_map = {i["key"]: i for i in context["investors"]}
    lines = ["=== 海外投資家・信託銀行 現物／先物クロス詳細 ==="]

    for inv_key, inv_label in [("foreign", "海外投資家"), ("trust_bank", "信託銀行")]:
        inv = inv_map.get(inv_key, {})
        spot_net = inv.get("spot_net", 0) or 0
        lines.append(f"\n【{inv_label}】")
        lines.append(f"  現物ネット    : {_fmt_net(spot_net)}")
        for ft in FUTURES_TYPE_ORDER:
            if ft not in data:
                continue
            d = data[ft][inv_key]
            if d["net_lots"] == 0 and d["net_oku"] == 0.0:
                continue
            lines.append(
                f"  {FUTURES_TYPE_JP.get(ft, ft):<16}: "
                f"{d['net_lots']:+,}枚 / {d['net_oku']:+.1f}億円"
            )
        # 商品をまたぐ生枚数の合計は経済量として無意味なため、合計は金額のみを渡す
        # （枚数合計を渡すとレポート本文に転記される事故が起きる）
        total_oku = sum(data[ft][inv_key]["net_oku"] for ft in data)
        lines.append(f"  先物合計（金額のみ）: {_fmt_net(total_oku)}")
        combined = inv.get("combined_net", 0) or 0
        lines.append(f"  現物＋先物合算: {_fmt_net(combined)}")
        spot_z    = f"{inv['zscore_52w']:+.2f}"         if inv.get("zscore_52w")         is not None else "―"
        futures_z = f"{inv['futures_zscore_52w']:+.2f}" if inv.get("futures_zscore_52w") is not None else "―"
        lines.append(f"  現物Zスコア(52w): {spot_z}  先物Zスコア(52w): {futures_z}")

    return "\n".join(lines)


def _build_data_table(context: dict) -> str:
    """分析コンテキストから簡易テーブル文字列を生成"""
    lines = []
    lines.append("=== 現物 投資家別売買（億円）===")
    lines.append(f"{'投資家':<12} {'現物買い':>12} {'現物売り':>12} {'現物ネット':>12} {'特記'}")
    lines.append("-" * 64)
    for inv in context["investors"]:
        tag = ""
        if inv.get("key") == "dealer":
            tag = "[自己:MM・在庫・顧客反対売買を含む(方向性判定対象外・MMと同一視しない)]"
        elif inv.get("is_twin_buy"):
            tag = "[両輪買い:Twin-Buy]"
        elif inv.get("is_twin_sell"):
            tag = "[両輪売り:Twin-Sell]"
        lines.append(
            f"{inv['label']:<12}"
            f" {inv.get('spot_buy', 0):>12,.1f}"
            f" {inv.get('spot_sell', 0):>12,.1f}"
            f" {_fmt_net(inv['spot_net']):>12}"
            f"  {tag}"
        )

    lines.append("")
    lines.append("=== 先物＋合算 投資家別集計 ===")
    lines.append(f"{'投資家':<12} {'先物換算':>12} {'合算':>12} {'現物Z(52w)':>12} {'先物Z(52w)':>12} {'前週比':>12} {'特記'}")
    lines.append("-" * 95)
    for inv in context["investors"]:
        tag = ""
        if inv.get("key") == "dealer":
            tag = "[自己:MM・在庫・顧客反対売買を含む(方向性判定対象外・MMと同一視しない)]"
        elif inv.get("is_twin_buy"):
            tag = "[両輪買い:Twin-Buy]"
        elif inv.get("is_twin_sell"):
            tag = "[両輪売り:Twin-Sell]"
        spot_z    = f"{inv['zscore_52w']:+.2f}"         if inv.get("zscore_52w")         is not None else " ―"
        futures_z = f"{inv['futures_zscore_52w']:+.2f}" if inv.get("futures_zscore_52w") is not None else " ―"
        wow       = _fmt_diff(inv.get("wow_change"))
        lines.append(
            f"{inv['label']:<12}"
            f" {_fmt_net(inv['futures_net']):>12}"
            f" {_fmt_net(inv['combined_net']):>12}"
            f" {spot_z:>12}"
            f" {futures_z:>12}"
            f" {wow:>12}"
            f"  {tag}"
        )

    futures_rows = context.get("futures_rows", [])
    if futures_rows:
        lines.append("")
        lines.append(_build_futures_breakdown(futures_rows))
        lines.append("")
        lines.append(_build_nt_bias_facts(futures_rows))
        lines.append("")
        lines.append(_build_spot_futures_detail(context, futures_rows))

    # オプション集計（存在する場合のみ追加）
    options_rows = context.get("options_rows", [])
    if options_rows:
        lines.append("")
        lines.append(_build_options_table(options_rows))

    return "\n".join(lines)


def generate_weekly_report(week_date: date, context: dict,
                           mode: str = "weekly",
                           market_data: dict | None = None,
                           generated_at: datetime | None = None) -> str:
    """
    Claude APIを呼び出して週次レポートのMarkdownを生成する

    Parameters
    ----------
    week_date : date
        集計基準日
    context : dict
        analyze_jpx.build_analysis_context() の返り値
    mode : str
        'weekly' or 'monthly'
    market_data : dict | None
        CLIから渡す市場数値。例: {"vix": 18.5, "nikkei_vi": 22.0, "usdjpy": 143.5}
        指定した項目はファイルの記述より優先される。
    generated_at : datetime | None
        レポート作成日時（JST）。省略時は現在時刻。
        対象週の翌週が作成時点で「未到来 / 進行中 / 経過済み」のどれかを判定し、
        経過済みの期間を「来週の注目点」として書かせないために使う。
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    as_of = generated_at or datetime.now(JST)

    # 知識ファイルを読み込み
    micro_flows    = _load_reference("jpx_micro_flows.md")
    gex_master     = _load_reference("options_gex_master.md")
    macro_dynamics = _load_reference("global_macro_dynamics.md")
    quant_tech     = _load_reference("quant_tech_psychology.md")

    # 市場データ（CLI引数で渡された場合のみ補足として追加）
    extra_market = ""
    if market_data:
        mapping = {
            "vix":       "VIX",
            "nikkei_vi": "日経VI",
            "usdjpy":    "USD/JPY",
            "us10y":     "米10年債利回り",
            "nk225":     "日経225終値",
        }
        items = [f"{label}: {market_data[k]}" for k, label in mapping.items() if k in market_data]
        if items:
            extra_market = "（参考数値: " + "、".join(items) + "）"

    data_table = _build_data_table(context)

    # ── system は2ブロックに分割 ────────────────────────────────
    # ブロック1（固定・キャッシュ対象）: 役割定義 + リファレンス4ファイル
    # ブロック2（動的）: 対象週・市場数値など毎回変わる部分
    static_system = f"""あなたはJPX投資主体別売買動向の専門アナリストです。
毎週木曜日に発表されるJPXデータを分析し、投資判断に直結する需給レポートを生成します。

## 【最重要】数値の符号規約（絶対に間違えないこと）

データテーブル内の金額（億円）は以下の符号規約に従っています：
- **正の値（+5,572.8 等、または符号なし）= 買い越し（ネット・バイ）**
- **負の値（-7,272.0 等のマイナス符号付き）= 売り越し（ネット・セル）**

レポート本文では日本市場慣例の「▲（買い越し）」「▼（売り越し）」を使って構いませんが、
**判定の根拠は必ず符号で行うこと**。会計上の「▲＝マイナス」用法と混同しないよう、
データテーブルの符号を最終確認してから「買い越し／売り越し」の判定を下すこと。

「両輪買い（Twin-Buy）」とは現物・先物の両方が正の値（買い越し）であること。
「両輪売り（Twin-Sell）」とは現物・先物の両方が負の値（売り越し）であること。
現物と先物の符号が逆方向の場合は「両輪」ではなく「裁定的／ヘッジ的」「方向性乖離」と表現すること。

{EXPRESSION_DISCIPLINE}

## オプションフローの解釈ルール（3段階を必ず区別する）

データには日経225オプション（標準・ミニ）の投資家別 net 枚数が含まれる場合があります。
TOPIXオプション・JPX日経400オプションは原資産・乗数が異なるため、日経225とは別項目として扱い、
同じ表・同じ合計に混ぜないこと。

### 第1段階: 確認できるフロー（事実）
- **規模の比較・合算は同一原資産内で「標準換算枚数（= 標準 + mini÷10）」で行う**。
  miniの乗数は標準の1/10であり、生枚数の単純合算は経済量として無意味（データに標準換算値を併記済み）。
- 確認できるのは「コール net の買い越し／売り越し」「プット net の買い越し／売り越し」の
  向きと規模まで。ここまでが事実である。

### 第2段階: 解釈（必ず「示唆」「可能性」を付ける）
- プット買い越し優位 → 下方向の保護需要または弱気方向のフローを示唆
- プット売り越し優位 → プレミアム受取または横ばい〜強気想定のフローを示唆
- コール買い越し優位 → 上方向の参加需要またはロングガンマ取得を示唆
- コール売り越し優位 → 上方向の抑制要因またはプレミアム受取のフローを示唆

### 第3段階: 取引目的（確認不能。断定禁止）
既存ロングのヘッジ / 新規の弱気ポジション / スプレッドの一部 / 既存ポジションの手仕舞い の
いずれであるかは、限月・行使価格・新規/転売区分・建玉増減が無いため分解できません。
「ヘッジを行った」「保険を掛けている」「リスクオフ志向」等と目的・姿勢で断定せず、
「目的は確認不能」と明記してください。「ベア・コンビネーション」「ブル・コンビネーション」等の
戦略名も、同一限月・同一行使価格・同時性が確認できないため使いません。
エグゼクティブサマリーでも同じ規律を適用し、「下方ヘッジ姿勢」を確定事実として要約しないこと。

### Proxy GEX 環境判定への寄与
- 判定の基礎は**自己部門のコール＋プット合計（標準換算）のネット方向**とする。
  オプションの買い手＝ロングガンマ、売り手＝ショートガンマ。合計が売り越し方向なら
  -GEX方向のバイアス、買い越し方向なら +GEX方向のバイアスが示唆される。
  コール/プットや標準/miniで方向が割れる場合は「混在」と明記する。
- **自己部門＝MMではない**。自己部門にはMMのほか在庫・顧客注文の反対売買等が含まれ、
  週間フローは建玉在庫ではない。「自己（MM）のガンマ・ポジション」という見出しを使わず、
  「自己部門を用いたProxy GEX判定」と書き、この留保を本文に明記すること。
- 行使価格別建玉・限月・Gamma・原資産との距離のデータが無いため**確定的なGEX判定は不可**。
  「-GEX環境である」「ディーラーはネガティブガンマ」と断定せず、
  「週間フローからは-GEX方向のバイアスが示唆される（Proxy判定）」と表現する。
- -GEX方向のバイアスが示唆される場合でも、裸のオプション売り（ネイキッド・ショート）は推奨しない。

「現物先物の方向性乖離」とオプションフローの関係は「同方向のフローとして整合する」までで表現し、
海外勢の「姿勢」「意図」「リスク管理方針」を断定しないでください。

## 参照知識（解釈フレームワークとして活用）

### 投資家行動原理・CVD解釈
{micro_flows}

### GEX環境判定・オプション戦略
{gex_master}

### マクロ文脈・季節性アノマリー
{macro_dynamics}

### Zスコア解釈・統計的分析・アルゴリズム行動原理
{quant_tech}
"""

    dynamic_system = f"""## 重要：分析基準日

**本レポートの対象週は {week_date}（{week_date.year}年）です。**
GEX判定・季節性アノマリー・マクロ環境の解釈はすべてこの日付を基準にしてください。
過去の特定イベント（例：関税ショック、特定の戦争・政策等の固有名詞）を
原因として断定的に言及しないこと。外部リスク要因は「地政学的不確実性」
「外部ショック」等の一般表現を使うこと。{extra_market}
{_build_time_axis_facts(week_date, as_of)}{_build_sq_facts(week_date)}{_build_calendar_facts(week_date)}{_build_scheduled_flow_note(week_date)}"""

    # 週初日（月曜）と週末日（金曜）の表記を計算
    week_start = week_date - timedelta(days=4)
    period_label = f"{week_start.strftime('%Y年%m月%d日')}〜{week_date.strftime('%m月%d日')}"

    user_prompt = f"""以下のJPX需給データ（{period_label} の週）を分析し、
Markdownレポートを生成してください。

{data_table}

## レポート要件

以下の構成で出力してください：

```
# JPX投資家別売買動向 {period_label}

> データソース: JPX投資部門別売買状況（株式週間売買状況 / 投資部門別売買状況）
> 対象期間: {period_label}（月〜金）

---

## 📋 エグゼクティブサマリー
（3〜5行で市場全体の需給を要約）

## 🌍 マクロ・市場環境
- GEX環境: [+GEX / -GEX の判定と根拠]
- 季節性アノマリー: [今週・今月に該当するイベント]
- 注目マクロ: [日銀・FRBイベント、IMM円ポジション等]

## 📊 現物（東証プライム）：投資家別売買
（テーブル形式で全5区分）

## 📈 先物（日経225・TOPIX）：商品種別×投資家 内訳
データに含まれる先物内訳テーブル（日経225ラージ/ミニ・TOPIXラージ/ミニ）をそのままMarkdownテーブルとして転記し、
各セルに枚数と億円換算を記載すること。

## 🔢 合算（現物＋先物換算）
（テーブル形式）

## 🔍 注目セグメント動向
### 🔵 海外投資家（必須・最詳細に）
- 現物・先物（日経225ラージ/ミニ・TOPIXラージ/ミニ）の個別数値を列挙し、商品別の強弱感の違いを解説する
- 日経225先物とTOPIX先物の方向性の違いを必ず分析すること。**日経225とTOPIXの規模比較・優劣判定は
  実約定金額ネット（億円）のみで行い**、ラージ換算を含む枚数で「どちらが大きい」と比較しないこと
  （枚数は同一原資産内のラージ/ミニ統合にのみ使う）
- NTロング／NTショートの語は、データ末尾の「NT方向（機械判定による事実）」の分類に従うこと。
  両指数が同符号の週はこれらの語を使わず、「両指数とも買い越し（TOPIX優位）」のように書く
- 現物と先物の方向性の一致・乖離を解釈すること（「ヘッジ」「リスクオン」等の目的は断定せず可能性に留める）
- Zスコアを踏まえた統計的な強弱の評価を含めること

### 🟢 信託銀行（必須・詳細に）
- 現物・先物（日経225ラージ/ミニ・TOPIXラージ/ミニ）の個別数値を列挙すること
- 信託銀行の先物の使われ方（ヘッジ・インデックスリバランス・テールリスクヘッジ等）は
  **可能性を並べて評価**し、いずれか一つに断定しないこと
- 海外投資家と信託銀行の**集計上の対応関係**（例:「一方の買い越しに対し他方が売り越し」）を記述すること。
  ネット集計から相対取引の相手方は特定できないため「カウンターパーティ」と断定しないこと

### 🟡 個人投資家
### 🟤 投資信託
（特異動向があれば事業法人・自己も）

## 🎯 オプションフロー分析（日経225標準＋ミニ／TOPIX・JPX400は別掲）
データにオプション売買差引が含まれる場合のみ出力:
- **オプションデータに含まれる全投資家**の **コール/プット別 net 枚数（生枚数と標準換算の両方）** をテーブルで提示
  （生枚数の内訳なしに標準換算値だけを引用しない）
- 標準換算の表題は必ず「**日経225オプション標準換算net**」とし、TOPIXオプション・JPX400オプションは
  原資産別の別項目として記載すること。3商品を合算した「全体net」を作らない
- **海外のプット net ≷ コール net** の比較は**日経225の標準換算枚数**で行う。
  向き（買い越し/売り越し）と規模までを事実として書き、目的（ヘッジか弱気か手仕舞いか）は「確認不能」と明記する
- **自己部門のコール＋プット合計（標準換算）のネット方向**から **Proxy GEX判定**を行う
  （±GEXバイアスは「示唆」表現・内訳併記・方向が割れれば「混在」）。
  見出しを「自己（MM）のガンマ・ポジション」とせず「自己部門を用いたProxy GEX判定」とし、
  自己部門がMMのほか在庫・顧客反対売買を含むこと、週間フローが建玉在庫でないことを本文に明記する
- 現物・先物の方向性乖離との整合性を「同方向のフローとして整合する」までで解説する
- データが空（過去週でオプションデータ未投入）の場合は本セクションを省略してよい

## 📅 先週比・Zスコア分析
（統計的な位置付けを言及）

## 💡 戦略示唆
- Proxy GEX判定に応じた推奨アプローチ（条件付きで書き、断定しない）
- 対象週の翌週に関する項目の見出しは、system の「時間軸（機械判定による事実）」の判定に従うこと
  （FUTURE=「次週の注目点」／ IN_PROGRESS=「進行中の週の残存監視項目」／ PAST=「対象週の翌週の事後検証項目」）。
  作成時点で既に経過した日を「今後の警戒事項」として書かないこと
- 反転確認シグナルは「□」のチェックリスト形式（5項目以上）で列挙すること
```

## 注意事項
- **符号の解釈を絶対に間違えないこと**：データテーブルの正値=買い越し、負値=売り越し。レポート本文で「▲/▼」を使う場合は買い越し=▲、売り越し=▼で統一すること
- **両輪買い／両輪売りの判定は現物と先物の符号が一致した場合のみ**。符号が逆（例: 現物=正、先物=負）の場合は「両輪」とは呼ばず「裁定的／方向性乖離」と表現する
- 先物内訳テーブルは必ずMarkdownテーブル形式で出力すること（省略不可）
- 「両輪買い（Twin-Buy）」が確認された場合は強気方向の強いシグナルとして必ず明記する（自己部門は判定対象外）
- 信託銀行の売買は「GPIF等の年金リバランスを含む可能性がある信託銀行フロー」と表現し、GPIFと同一視しないこと。
  「健全な上昇の証左」等の価値判断を根拠なく添えない
- Zスコアが±2.0を超えている場合は統計的に異常な水準として言及する
- 季節性アノマリー（SQ週・月末・4月効果・7月上旬のETF分配金捻出売り・8月夏枯れ等）に該当する場合は必ず記載する。SQ日程はsystemの「SQ日程（機械計算による事実）」のみを根拠とすること
- 投資家セグメント内で先物内訳（日経225ラージ/ミニ・TOPIXラージ/ミニ）を列挙した後の「先物合計」行は必ず**金額（億円）のみ**で記載し、商品をまたぐ合計枚数（例:「先物合計: -20,543枚」）は絶対に記載しない
- 日経225とTOPIXの**枚数（ラージ換算を含む）を「約3倍」等と規模比較しない**。原資産をまたぐ規模比較は金額のみ
- 表示対象は6主体のみで全投資部門を網羅していない。「唯一」と書く場合は「表示対象6主体の中で唯一」と範囲を明示する
- 規模の区分語（ノイズ／小〜中／大／超大）を使う場合は、参照知識の量的感覚スケールに基づく本レポート規定の区分であることを明記する
- 許容損失率（「総資金の2%」等）・具体的な建玉枚数・投入金額は本データから導けない。記載する場合は「別途定めた資金管理ルール」と明示する
- 客観的・簡潔に。投資家が実際に使えるコメントを目指す
- 「関税ショック」「○○戦争」等の特定イベント固有名詞は断定的に使わず「外部ショック」「地政学的不確実性」等の一般表現を使うこと
"""

    model = _get_model()
    logger.info(f"[AIエージェント] レポート生成開始 (model={model})...")
    with client.messages.stream(
        model=model,
        max_tokens=MAX_TOKENS,
        thinking=THINKING,
        system=[
            {
                "type": "text",
                "text": static_system,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": dynamic_system,
            },
        ],
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        message = stream.get_final_message()

    # thinkingブロックが先頭に付くモデル（Opus 5・Sonnet 5等）でも動くようtextブロックのみ抽出
    report_md = "\n".join(b.text for b in message.content if b.type == "text")
    _log_cache_usage(message, label="週次")
    if message.stop_reason == "max_tokens":
        logger.warning(f"[AIエージェント] 週次レポートがmax_tokens上限で途中切断 ({len(report_md)}文字)")
    logger.info(f"[AIエージェント] レポート生成完了 ({len(report_md)}文字)")

    _run_report_lint(report_md, context, week_date, as_of)
    return report_md


def _run_report_lint(report_md: str, context: dict,
                     week_date: date, as_of: datetime) -> list[dict]:
    """生成後の公開前チェック。違反はWARNINGでログに出す（生成は止めない）。"""
    from agents import report_lint

    futures_rows = context.get("futures_rows", [])
    nt_classifications = {
        inv: classify_nt_bias(v["nikkei"], v["topix"])["classification"]
        for inv, v in nt_amounts_by_investor(futures_rows).items()
    } if futures_rows else None

    next_start = week_date + timedelta(days=3)
    next_end   = week_date + timedelta(days=7)
    state = classify_period(as_of.date(), next_start, next_end)

    findings = report_lint.lint_weekly_report(
        report_md, nt_classifications=nt_classifications, next_week_state=state)

    _write_lint_result(findings)

    if not findings:
        logger.info("[公開前チェック] 違反なし")
        return findings

    n_p0 = sum(1 for f in findings if f["severity"] == report_lint.SEVERITY_P0)
    logger.warning(f"[公開前チェック] {len(findings)}件検出（P0={n_p0}件）")
    for line in report_lint.format_findings(findings):
        logger.warning(f"  {line}")
    if n_p0:
        logger.warning("  → P0はレポートの結論が反転し得る違反です。内容を確認し再生成を検討してください。")
    return findings


def _write_lint_result(findings: list[dict]) -> None:
    """公開前チェックの結果をファイルに残す。

    GitHub Actions のログは能動的に見に行かないと気づけないため、
    後続ステップのサマリーメール（scripts/send_summary_mail.py）から読めるようにする。
    """
    from agents import report_lint

    out_dir = Path(os.environ.get("OUTPUT_DIR", "./outputs"))
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        body = "\n".join(report_lint.format_findings(findings)) if findings else "OK"
        (out_dir / "last_lint.txt").write_text(body + "\n", encoding="utf-8")
    except Exception as e:  # 書けなくてもレポート生成は継続する
        logger.warning(f"[公開前チェック] 結果ファイルの書き込みに失敗: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 月次レポート
# ─────────────────────────────────────────────────────────────────────────────

_INV_ORDER = ["foreign", "trust_bank", "individual", "inv_trust", "corporate", "dealer"]
_INV_SHORT = {
    "foreign":    "海外",
    "trust_bank": "信託",
    "individual": "個人",
    "inv_trust":  "投信",
    "corporate":  "事業法人",
    "dealer":     "自己",
}


def _build_monthly_data_table(monthly_rows: list[dict], target_month: str) -> str:
    """月次サマリー行をAIプロンプト用のテキストテーブルに整形する。

    monthly_rows は fetch_monthly_summary() の返り値（year_month降順）。
    target_month = "YYYY-MM"
    """
    from collections import defaultdict

    # {year_month: {investor_type: row}} に再編成
    pivot: dict[str, dict] = defaultdict(dict)
    for r in monthly_rows:
        pivot[r["year_month"]][r["investor_type"]] = r

    months_sorted = sorted(pivot.keys(), reverse=True)[:13]  # 最大13ヶ月

    header_invs = [k for k in _INV_ORDER if k in _INV_SHORT]
    col_header  = " | ".join(f"{_INV_SHORT[k]:^8}" for k in header_invs)
    separator   = "-|-".join(["-" * 8] * (len(header_invs) + 1))

    def make_table(field: str, label: str) -> str:
        lines = [f"### {label}（億円）", f"| {'年月':^7} | {col_header} |", f"|{separator}|"]
        for ym in months_sorted:
            cells = []
            for inv in header_invs:
                val = pivot[ym].get(inv, {}).get(field)
                if val is None:
                    cells.append(f"{'―':^8}")
                else:
                    sign = "▲" if val < 0 else "+"
                    cells.append(f"{sign}{abs(val):>6,.0f}".center(8))
            marker = " ★今月" if ym == target_month else ""
            lines.append(f"| {ym} | {' | '.join(cells)} |{marker}")
        return "\n".join(lines)

    parts = [
        f"## 月次需給データ（対象: {target_month}）",
        "",
        make_table("spot_net_sum",    "現物 NET（買い越し=+）"),
        "",
        make_table("futures_net_sum", "先物 NET（買い越し=+）"),
        "",
        make_table("combined_net",    "合算 NET（現物＋先物）"),
    ]

    # 今月の週数を追記
    today_data = pivot.get(target_month, {})
    week_count = next((v.get("week_count", "?") for v in today_data.values()), "?")
    parts.append(f"\n※ {target_month} は {week_count} 週分を集計")

    return "\n".join(parts)


def generate_monthly_report(year_month: str, monthly_rows: list[dict],
                            index_data: dict | None = None) -> str:
    """月次需給レポートを生成する。

    Parameters
    ----------
    year_month : str
        対象年月 "YYYY-MM"
    monthly_rows : list[dict]
        fetch_monthly_summary() の返り値（直近13ヶ月分推奨）
    index_data : dict | None
        実勢の指数終値アンカー。例:
        {"month_end": ("2026-05-29", 66329.5), "latest": ("2026-06-05", 66588.12)}
        渡されない場合、プロンプト側で具体的な株価水準への言及を禁止する。
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    micro_flows    = _load_reference("jpx_micro_flows.md")
    macro_dynamics = _load_reference("global_macro_dynamics.md")
    quant_tech     = _load_reference("quant_tech_psychology.md")

    data_table = _build_monthly_data_table(monthly_rows, year_month)

    # ── system は2ブロックに分割（キャッシュ対象=固定知識、動的=対象月） ──
    static_system = f"""あなたはJPX投資主体別売買動向の専門アナリストです。
月次の需給データを分析し、中期（1〜3ヶ月）の市場トレンドを把握する
月次需給レポートを生成します。週次レポートとは異なり、短期ノイズを除いた
中期トレンドの把握・転換点の特定・季節性アノマリーの評価を重視してください。

{EXPRESSION_DISCIPLINE}

## 参照知識

### 投資家行動原理・CVD解釈
{micro_flows}

### マクロ文脈・季節性アノマリー
{macro_dynamics}

### Zスコア解釈・統計的分析
{quant_tech}
"""

    # ── 指数終値アンカー（価格ハルシネーション防止） ──
    if index_data:
        anchor_lines = []
        if index_data.get("month_end"):
            d, c = index_data["month_end"]
            anchor_lines.append(f"- {year_month} 月末終値（{d}）: 日経225 = {c:,.0f}円")
        if index_data.get("latest"):
            d, c = index_data["latest"]
            anchor_lines.append(f"- 直近終値（{d}）: 日経225 = {c:,.0f}円")
        price_block = f"""## 実勢の指数水準（唯一の価格根拠）

{chr(10).join(anchor_lines)}

価格水準・株価目標・レンジに言及する場合は、**必ず上記の実勢終値のみを基準**にしてください。
あなたの記憶や学習データ上の株価水準は古く、実勢と大きく乖離している可能性があります。
上記以外の指数水準を根拠なく持ち出すことは厳禁です。
"""
    else:
        price_block = """## 価格水準への言及禁止

本レポートには実勢の指数終値データが提供されていません。
したがって**具体的な株価水準・指数レンジ・株価目標（「○○円台」等）には一切言及しないでください。**
見通しは需給フロー（買い越し/売り越しの方向と規模）のみで定性的に述べてください。
"""

    # 7月は国内株ETFの決算・分配金捻出売り（例年7/8・7/10集中）を含む
    scheduled_flow_note = ""
    if year_month[5:7] == "07":
        scheduled_flow_note = """
## 【Scheduled Flow】国内株ETFの決算・分配金捻出売り（毎年7月上旬の年次イベント）

対象月には国内株ETF（日経225・TOPIX連動の主要ETF）の決算日（例年7月8日・10日に集中）が
含まれる。投資信託等の当月売り越しには、分配金支払いの原資を捻出するための機械的な
換金売り（Scheduled Flow）が相当程度含まれている可能性がある。
月次ネット集計からは機械的フローと方向性売買を分解できないため、
「一部含まれる可能性が高い」までに留め、当月の売り越しを恒常的な資金流出・
継続的な弱気判断と断定しないこと。前後月との比較でイベント要因の剥落を確認すること。
"""

    dynamic_system = f"""## 重要：分析対象月

**本レポートの対象月は {year_month} です。** すべての分析・季節性判定はこの月を基準にしてください。

{price_block}{scheduled_flow_note}"""

    user_prompt = f"""以下のJPX月次需給データ（{year_month}）を分析し、
月次需給レポートをMarkdown形式で生成してください。

{data_table}

## レポート要件

以下の構成で出力してください：

```
# JPX投資家別売買動向 月次レポート {year_month}

> データソース: JPX投資部門別売買状況（月次集計）

---

## 📋 エグゼクティブサマリー
（{year_month}の需給を3〜5行で要約。中期トレンドの変化・継続を中心に）

## 📊 月次需給テーブル（転記）
（データの現物・先物・合算テーブルをそのままMarkdownテーブルとして転記すること）

## 🔍 投資家別 中期トレンド分析

### 🔵 海外投資家（最重要・最詳細に）
- 直近3ヶ月・6ヶ月・12ヶ月の累積フロー（現物・先物・合算）
- 連続買い越し/売り越しの継続月数と累積金額
- トレンドの強度（加速・減速・転換）
- 季節性アノマリーとの比較（前年同月比）

### 🟢 信託銀行
- 中期的な売買方向とリバランス解釈（GPIFと同一視せず「年金リバランスを含む可能性」に留める）
- 海外投資家との集計上の対応関係の変化（「カウンターパーティ」と断定しない）

### 🟡 個人投資家
- 逆張り/順張りパターンの継続性

### 🟤 投資信託
（特異動向があれば事業法人・自己も）

## 📅 季節性・アノマリー分析
- {year_month[:4]}年{year_month[5:]}月に該当する季節性イベント
- 前年同月との需給比較
- SQ・決算・配当・MSCI等のイベント影響

## 💡 中期見通しと戦略示唆
- 今後1〜3ヶ月の需給見通し（強気/中立/弱気の根拠）
- 注目すべきトレンド転換シグナル
- 来月の需給チェックポイント
```

## 注意事項
- 月次テーブルは必ずMarkdownテーブル形式で転記すること（省略不可）
- 連続買い越し/売り越しの月数を具体的に数えて記載すること
- 単月の異常値だけでなく、3〜6ヶ月スパンのトレンドを重視すること
- 客観的・簡潔に。投資家が中期戦略の参考にできる内容を目指す
- **株価水準・指数レンジ・株価目標に言及する場合は、system に記載の「実勢の指数水準」のみを根拠とすること。**
  実勢データが提供されていない場合は、具体的な株価水準には一切触れず、需給フローの方向性のみで見通しを述べること。
  あなたの記憶上の日経平均水準は古く実勢と乖離しているため、絶対に使わないこと。
"""

    model = _get_model()
    logger.info(f"[AIエージェント] 月次レポート生成開始: {year_month} (model={model})")
    with client.messages.stream(
        model=model,
        max_tokens=MAX_TOKENS,
        thinking=THINKING,
        system=[
            {
                "type": "text",
                "text": static_system,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": dynamic_system,
            },
        ],
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        message = stream.get_final_message()

    # thinkingブロックが先頭に付くモデル（Opus 5・Sonnet 5等）でも動くようtextブロックのみ抽出
    report_md = "\n".join(b.text for b in message.content if b.type == "text")
    _log_cache_usage(message, label="月次")
    if message.stop_reason == "max_tokens":
        logger.warning(f"[AIエージェント] 月次レポートがmax_tokens上限で途中切断 ({len(report_md)}文字)")
    logger.info(f"[AIエージェント] 月次レポート生成完了 ({len(report_md)}文字)")
    return report_md
