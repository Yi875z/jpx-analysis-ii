"""
agents/report_agent.py
Claude APIを呼び出して解釈付き週次レポートを生成するエージェント
"""

import json
import logging
import os
from datetime import date
from pathlib import Path
import anthropic

logger = logging.getLogger(__name__)

SKILL_REFS_DIR = Path(__file__).parent.parent / "skills" / "jpx-investor-data" / "references"

# 使用モデルは .env の CLAUDE_MODEL で切替可能（未設定時は Sonnet 4.6）
DEFAULT_MODEL = "claude-sonnet-4-6"


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
BREAKDOWN_INVESTORS = ["foreign", "trust_bank", "individual", "inv_trust", "dealer"]
BREAKDOWN_LABELS = {
    "foreign":    "海外投資家",
    "trust_bank": "信託銀行",
    "individual": "個人",
    "inv_trust":  "投資信託",
    "dealer":     "自己",
}

# オプションは投資信託(inv_trust)カラムがDBに無い場合があるため、
# 投資家コード対応の "investment_trust" にもフォールバック
OPTION_TYPE_JP = {
    "nikkei225_call":      "日経225オプション コール",
    "nikkei225_put":       "日経225オプション プット",
    "nikkei225_mini_call": "日経225miniオプション コール",
    "nikkei225_mini_put":  "日経225miniオプション プット",
}
OPTION_TYPE_ORDER = ["nikkei225_call", "nikkei225_put", "nikkei225_mini_call", "nikkei225_mini_put"]
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
        "=== 日経225オプション 投資家別 売買差引（net、正=買い越し / 負=売り越し）===",
        "  表記: 枚数 / 億円 (プレミアム金額換算、負=プレミアム支払超過、正=プレミアム受取超過)",
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

    # 海外投資家のヘッジ姿勢ヒント（プット買い vs コール買いの比較）
    fdata = data.get("foreign", {})
    fp = fdata.get("nikkei225_put", {}).get("net_lots", 0) + fdata.get("nikkei225_mini_put", {}).get("net_lots", 0)
    fc = fdata.get("nikkei225_call", {}).get("net_lots", 0) + fdata.get("nikkei225_mini_call", {}).get("net_lots", 0)
    if fp != 0 or fc != 0:
        lines.append("")
        lines.append(
            f"※ 海外投資家のオプション差引（標準＋ミニ合算）: "
            f"プット net {fp:+,}枚、コール net {fc:+,}枚 "
            f"(プット買い越し優位 = 下方ヘッジ姿勢、コール買い越し優位 = 上方期待)"
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
    lines = ["=== 先物内訳（商品種別×投資家）枚数 / 億円 ==="]
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

    lines.append("-" * (18 + (col_w + 1) * len(BREAKDOWN_INVESTORS)))
    totals_lots: dict = defaultdict(int)
    totals_oku:  dict = defaultdict(float)
    for ft in data:
        for inv in BREAKDOWN_INVESTORS:
            totals_lots[inv] += data[ft][inv]["net_lots"]
            totals_oku[inv]  += data[ft][inv]["net_oku"]
    total_row = f"{'合計（全商品）':<18}"
    for inv in BREAKDOWN_INVESTORS:
        cell = f"{totals_lots[inv]:+,}枚/{totals_oku[inv]:+.0f}億"
        total_row += f" {cell:>{col_w}}"
    lines.append(total_row)

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

    for inv_key, inv_label in [("foreign", "海外投資家"), ("trust_bank", "信託銀行（GPIF）")]:
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
        total_lots = sum(data[ft][inv_key]["net_lots"] for ft in data)
        total_oku  = sum(data[ft][inv_key]["net_oku"]  for ft in data)
        lines.append(f"  先物合計      : {total_lots:+,}枚 / {_fmt_net(total_oku)}")
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
    lines.append(f"{'投資家':<12} {'現物買い':>10} {'現物売り':>10} {'現物ネット':>12} {'特記'}")
    lines.append("-" * 60)
    for inv in context["investors"]:
        tag = ""
        if inv.get("is_twin_buy"):
            tag = "[両輪買い:Twin-Buy]"
        elif inv.get("is_twin_sell"):
            tag = "[両輪売り:Twin-Sell]"
        lines.append(
            f"{inv['label']:<12}"
            f" {inv.get('spot_buy', 0):>10,.0f}"
            f" {inv.get('spot_sell', 0):>10,.0f}"
            f" {_fmt_net(inv['spot_net']):>12}"
            f"  {tag}"
        )

    lines.append("")
    lines.append("=== 先物＋合算 投資家別集計 ===")
    lines.append(f"{'投資家':<12} {'先物換算':>12} {'合算':>12} {'現物Z(52w)':>12} {'先物Z(52w)':>12} {'前週比':>12} {'特記'}")
    lines.append("-" * 95)
    for inv in context["investors"]:
        tag = ""
        if inv.get("is_twin_buy"):
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
        lines.append(_build_spot_futures_detail(context, futures_rows))

    # オプション集計（存在する場合のみ追加）
    options_rows = context.get("options_rows", [])
    if options_rows:
        lines.append("")
        lines.append(_build_options_table(options_rows))

    return "\n".join(lines)


def generate_weekly_report(week_date: date, context: dict,
                           mode: str = "weekly",
                           market_data: dict | None = None) -> str:
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
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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

## 【新規】オプションフローの解釈ルール

データには日経225オプション（標準・ミニ）の投資家別 net 枚数が含まれる場合があります。
解釈の基本：
- **プット買い越し（net_lots > 0）= 下方ヘッジ・ボラ上昇期待・弱気バイアス**
- **プット売り越し（net_lots < 0）= プットライト/プレミアム獲得・横ばい〜強気想定**
- **コール買い越し = 上方期待・ロングガンマ取得（ボラ上昇期待）**
- **コール売り越し = カバードコール／レンジ想定／上方抑制要因**
- **海外投資家のプット買いが継続的・大規模** = 現物先物のヘッジ目的が明確（=リスクオン姿勢でも保険を掛けている）
- **コール売り＋プット買い（ベア・コンビネーション）** = リスクオフ志向
- **コール買い＋プット売り（ブル・コンビネーション）** = リスクオン志向

GEX 環境判定への寄与：
- **証券会社（dealer）のオプションネット** はマーケットメーカーのデルタヘッジ需要を映す
- **海外プット買い＋自己プット売り** が同時発生 → 自己（MM）がショートガンマを背負う = **-GEX（ボラ拡大環境）リスク**
- **海外プット売り＋自己プット買い** = 自己がロングガンマ = **+GEX（Pinning安定環境）**

「現物先物の方向性乖離」とオプションフローを必ずセットで分析し、海外勢のリスク管理姿勢を立体的に解釈すること。

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
"""

    # 週初日（月曜）と週末日（金曜）の表記を計算
    from datetime import timedelta as _td
    week_start = week_date - _td(days=4)
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
- 日経225先物（ラージ＋ミニ合算）とTOPIX先物（ラージ＋ミニ合算）の方向性の違いを必ず分析すること
- 現物と先物の方向性の一致・乖離（ヘッジvsリスクオン等）を解釈すること
- Zスコアを踏まえた統計的な強弱の評価を含めること

### 🟢 信託銀行（GPIF）（必須・詳細に）
- 現物・先物（日経225ラージ/ミニ・TOPIXラージ/ミニ）の個別数値を列挙すること
- 信託銀行の先物の使われ方（ヘッジ目的か、インデックスリバランスか、テールリスクヘッジか）を解釈すること
- 海外投資家と信託銀行の動向の相互関係（どちらがカウンターパーティになっているか）を分析すること

### 🟡 個人投資家
### 🟤 投資信託
（特異動向があれば事業法人・自己も）

## 🎯 オプションフロー分析（日経225標準＋ミニ）
データにオプション売買差引が含まれる場合のみ出力:
- 海外投資家・自己・個人の **コール/プット別 net 枚数** をテーブルで提示
- **海外プット買い ≷ コール買い** の比較から下方ヘッジ姿勢の強弱を判定
- **自己のプット net** から MM のガンマ・ポジション（+GEX / -GEX）を推定
- 現物・先物の方向性乖離との整合性（ヘッジ的フローの裏付けになっているか）を解説
- データが空（過去週でオプションデータ未投入）の場合は本セクションを省略してよい

## 📅 先週比・Zスコア分析
（統計的な位置付けを言及）

## 💡 戦略示唆
- GEX環境に応じた推奨アプローチ
- 来週の注目点・警戒事項
```

## 注意事項
- **符号の解釈を絶対に間違えないこと**：データテーブルの正値=買い越し、負値=売り越し。レポート本文で「▲/▼」を使う場合は買い越し=▲、売り越し=▼で統一すること
- **両輪買い／両輪売りの判定は現物と先物の符号が一致した場合のみ**。符号が逆（例: 現物=正、先物=負）の場合は「両輪」とは呼ばず「裁定的／方向性乖離」と表現する
- 先物内訳テーブルは必ずMarkdownテーブル形式で出力すること（省略不可）
- 「両輪買い（Twin-Buy）」が確認された場合は最強強気シグナルとして必ず明記する
- 信託銀行の売り越しは「GPIFリバランス＝健全な上昇の証左」として解釈する
- Zスコアが±2.0を超えている場合は統計的に異常な水準として言及する
- 季節性アノマリー（SQ週・月末・4月効果・8月夏枯れ等）に該当する場合は必ず記載する
- 客観的・簡潔に。投資家が実際に使えるコメントを目指す
- 「関税ショック」「○○戦争」等の特定イベント固有名詞は断定的に使わず「外部ショック」「地政学的不確実性」等の一般表現を使うこと
"""

    model = _get_model()
    logger.info(f"[AIエージェント] レポート生成開始 (model={model})...")
    message = client.messages.create(
        model=model,
        max_tokens=8192,
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
    )

    report_md = message.content[0].text
    _log_cache_usage(message, label="週次")
    logger.info(f"[AIエージェント] レポート生成完了 ({len(report_md)}文字)")
    return report_md


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


def generate_monthly_report(year_month: str, monthly_rows: list[dict]) -> str:
    """月次需給レポートを生成する。

    Parameters
    ----------
    year_month : str
        対象年月 "YYYY-MM"
    monthly_rows : list[dict]
        fetch_monthly_summary() の返り値（直近13ヶ月分推奨）
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

## 参照知識

### 投資家行動原理・CVD解釈
{micro_flows}

### マクロ文脈・季節性アノマリー
{macro_dynamics}

### Zスコア解釈・統計的分析
{quant_tech}
"""

    dynamic_system = f"""## 重要：分析対象月

**本レポートの対象月は {year_month} です。** すべての分析・季節性判定はこの月を基準にしてください。
"""

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

### 🟢 信託銀行（GPIF）
- 中期的な売買方向とリバランス解釈
- 海外投資家とのカウンターパーティ関係の変化

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
"""

    model = _get_model()
    logger.info(f"[AIエージェント] 月次レポート生成開始: {year_month} (model={model})")
    message = client.messages.create(
        model=model,
        max_tokens=8192,
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
    )

    report_md = message.content[0].text
    _log_cache_usage(message, label="月次")
    logger.info(f"[AIエージェント] 月次レポート生成完了 ({len(report_md)}文字)")
    return report_md
