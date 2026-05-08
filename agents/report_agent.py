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
    if val is None:
        return "-"
    mark = "▲" if val > 0 else "▼"
    return f"{mark}{abs(val):,.1f}億円"


def _fmt_diff(val: float | None) -> str:
    if val is None:
        return "-"
    return f"{'+' if val >= 0 else ''}{val:,.1f}"


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
            tag = "★両輪買い"
        elif inv.get("is_twin_sell"):
            tag = "▼両輪売り"
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
            tag = "★両輪買い"
        elif inv.get("is_twin_sell"):
            tag = "▼両輪売り"
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

    system_prompt = f"""あなたはJPX投資主体別売買動向の専門アナリストです。
毎週木曜日に発表されるJPXデータを分析し、投資判断に直結する需給レポートを生成します。

## 重要：分析基準日

**本レポートの対象週は {week_date}（{week_date.year}年）です。**
GEX判定・季節性アノマリー・マクロ環境の解釈はすべてこの日付を基準にしてください。
過去の特定イベント（例：関税ショック、特定の戦争・政策等の固有名詞）を
原因として断定的に言及しないこと。外部リスク要因は「地政学的不確実性」
「外部ショック」等の一般表現を使うこと。{extra_market}

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

    user_prompt = f"""以下のJPX需給データ（{week_date}週）を分析し、
Markdownレポートを生成してください。

{data_table}

## レポート要件

以下の構成で出力してください：

```
# JPX投資家別売買動向 {week_date.strftime('%Y年%m月%d日')}週

> データソース: JPX投資部門別売買状況

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

## 📅 先週比・Zスコア分析
（統計的な位置付けを言及）

## 💡 戦略示唆
- GEX環境に応じた推奨アプローチ
- 来週の注目点・警戒事項
```

## 注意事項
- 先物内訳テーブルは必ずMarkdownテーブル形式で出力すること（省略不可）
- 「両輪買い（Twin Engine）」が確認された場合は最強強気シグナルとして必ず明記する
- 信託銀行の売り越しは「GPIFリバランス＝健全な上昇の証左」として解釈する
- Zスコアが±2.0を超えている場合は統計的に異常な水準として言及する
- 季節性アノマリー（SQ週・月末・4月効果・8月夏枯れ等）に該当する場合は必ず記載する
- 客観的・簡潔に。投資家が実際に使えるコメントを目指す
- 「関税ショック」「○○戦争」等の特定イベント固有名詞は断定的に使わず「外部ショック」「地政学的不確実性」等の一般表現を使うこと
"""

    logger.info("[AIエージェント] レポート生成開始...")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    report_md = message.content[0].text
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

    system_prompt = f"""あなたはJPX投資主体別売買動向の専門アナリストです。
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

    logger.info(f"[AIエージェント] 月次レポート生成開始: {year_month}")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    report_md = message.content[0].text
    logger.info(f"[AIエージェント] 月次レポート生成完了 ({len(report_md)}文字)")
    return report_md
