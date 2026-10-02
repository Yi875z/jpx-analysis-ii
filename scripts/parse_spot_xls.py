import logging
import sys

import pandas as pd

logger = logging.getLogger(__name__)

# ======================================
# 現物XLSパーサー v2.0
# 修正日: 2026-04-06
# 修正点:
#   ① シート名を 'Tokyo & Nagoya' に変更（二市場合計が正式対象）
#   ② 読み取り列を col4 → col8 に変更（Tokyo & Nagoya の金額列）
#   ③ 単位変換を /1e8 → /1e5 に修正（千円 → 億円）
#   ④ "trust" (rows37-38) は投資信託（inv_trust）に訂正
#   ⑤ 信託銀行 (trust_bank) を rows57-58 から追加
#
# v3.0（2026-10-02）: JPX の新形式（2026-09-29 掲載分〜 stock_1_w_YYYYMMDD_YYYYMMDD.xlsx）に対応。
#   ファイルの中身（シート構成）で新旧を判定し、旧形式（stock_val_1_YYMMNN.xls）も従来どおり読む。
# ======================================

# (売り行, 買い行) ← col8 が Tokyo & Nagoya の金額（千円単位）
INVESTOR_ROWS = {
    "dealer":     (12, 13),   # 自己計
    "individual": (26, 27),   # 個人
    "foreign":    (29, 30),   # 海外投資家
    "inv_trust":  (37, 38),   # 投資信託
    "corporate":  (40, 41),   # 事業法人
    "trust_bank": (57, 58),   # 信託銀行
}

# 現物で必ず揃うべき投資部門（新旧どちらの形式でも同じ6主体）
SPOT_INVESTORS = tuple(INVESTOR_ROWS)

OLD_FORMAT_SHEET = "Tokyo & Nagoya"


# ======================================
# 新形式 v3.0（2026-09-29 掲載分〜）
# 1シートに縦＝市場（プライム/スタンダード/グロース/二市場）×（株数/金額）、
# 横＝投資部門（売・買・差引・合計の4列ずつ）が並ぶ。
#
# 旧形式の「自己計」「個人」「海外投資家」に当たる合計列は無く、内訳だけが載っている。
# そこで内訳を足して旧形式と同じ定義に揃える:
#   自己       = 現金取引 + 信用取引
#   個人       = 現金取引 + 信用取引
#   海外投資家 = 法人 + 個人
# 検証（2026-10-02）: JPX のサンプルファイル（2026年4月第1週）を上の合算で集計すると、
# 旧形式から取り込んだ DB の 2026-04-03 週の6主体の売り・買い・差引が小数2桁まで全て一致した
# （tests/test_spot_parser.py で回帰テスト化）。
# ======================================

# 投資部門 → 足し合わせる (売り列, 買い列) の組
NEW_FORMAT_GROUPS = {
    "dealer":     [("D", "E"), ("H", "I")],     # 自己: 現金 + 信用
    "individual": [("L", "M"), ("P", "Q")],     # 個人: 現金 + 信用
    "foreign":    [("T", "U"), ("X", "Y")],     # 海外投資家: 法人 + 個人
    "inv_trust":  [("AF", "AG")],               # 投資信託
    "corporate":  [("AJ", "AK")],               # 事業法人
    "trust_bank": [("AZ", "BA")],               # 信託銀行
}

# 列の意味を推測で決めないため、読む前に見出しセルの文言を照合する。
# JPX がまた配置を変えたら、ここで止まって気づける。
NEW_FORMAT_HEADERS = {
    "D3": "自己", "L3": "委託",
    "D4": "自己", "L4": "個人", "T4": "海外投資家",
    "D5": "現金取引", "H5": "信用取引",
    "L5": "現金取引", "P5": "信用取引",
    "T5": "法人", "X5": "個人",
    "AF5": "投資信託", "AJ5": "事業法人",
    "AZ6": "信託銀行",
    "C7": "千円",
}

# 単位の取り違え検知: 海外投資家の売買合計（億円）がこの範囲外なら単位が想定と違う。
# 通常の1週間は約50万億円（=50兆円）。祝日で2営業日の週でも20万億円台。
FOREIGN_GROSS_OKU_RANGE = (1e4, 5e6)


def _cell_text(ws, coord: str) -> str:
    v = ws[coord].value
    return "" if v is None else str(v).replace("　", "").replace(" ", "")


def _col_offset(col: str, n: int) -> str:
    from openpyxl.utils import column_index_from_string, get_column_letter
    return get_column_letter(column_index_from_string(col) + n)


def _find_two_market_value_row(ws) -> int:
    """「二市場」の「金額」行の行番号を返す。見つからなければ例外。"""
    for r in range(1, ws.max_row + 1):
        if _cell_text(ws, f"B{r}").startswith("二市場"):
            if "株数" not in _cell_text(ws, f"C{r}") or "金額" not in _cell_text(ws, f"C{r + 1}"):
                raise ValueError(f"二市場の株数/金額の行の並びが想定と違います（B{r}）")
            return r + 1
    raise ValueError("「二市場」の行が見つかりません")


def parse_spot_xlsx_v3(filepath, week_date):
    """新形式（stock_1_w_YYYYMMDD_YYYYMMDD.xlsx）から投資家別売買（二市場・金額）を返す。

    見出しの照合・差引の検算・単位の妥当性のどれかが合わなければ ValueError を投げる。
    部分的な結果は返さない（6主体そろうか、例外か）。
    """
    import openpyxl

    wb = openpyxl.load_workbook(filepath, data_only=True, read_only=False)
    if len(wb.worksheets) != 1:
        raise ValueError(f"新形式は1シートのはずが {len(wb.worksheets)} シートあります: {wb.sheetnames}")
    ws = wb.worksheets[0]

    for coord, expected in NEW_FORMAT_HEADERS.items():
        if expected not in _cell_text(ws, coord):
            raise ValueError(
                f"見出しが想定と違います: {coord}={ws[coord].value!r}（期待: {expected!r} を含む）"
            )

    row = _find_two_market_value_row(ws)
    week_code = ws["A8"].value  # 例: '2026094' = 2026年9月第4週（記録用）

    def num(coord: str) -> float:
        v = ws[coord].value
        if not isinstance(v, (int, float)):
            raise ValueError(f"数値でないセル: {coord}={v!r}")
        return float(v)

    results = []
    for inv_key, pairs in NEW_FORMAT_GROUPS.items():
        sell = buy = 0.0
        for sell_col, buy_col in pairs:
            if not _cell_text(ws, f"{sell_col}7").startswith("売") or \
               not _cell_text(ws, f"{buy_col}7").startswith("買"):
                raise ValueError(f"{inv_key}: 売/買の列見出しが想定と違います（{sell_col}7/{buy_col}7）")
            s, b = num(f"{sell_col}{row}"), num(f"{buy_col}{row}")
            # 差引列（売りの2列右）が 買−売 と一致するかで列のずれを検算する
            bal_col = _col_offset(sell_col, 2)
            if num(f"{bal_col}{row}") != b - s:
                raise ValueError(f"{inv_key}: 差引の検算が合いません（{bal_col}{row}）")
            sell += s
            buy += b
        results.append({
            "week_date":     week_date,
            "investor_type": inv_key,
            "buy_amount":    round(buy / 1e5, 2),           # 千円 → 億円
            "sell_amount":   round(sell / 1e5, 2),
            "net_amount":    round((buy - sell) / 1e5, 2),
            "market":        "prime",  # 旧形式と同じラベル（中身は二市場合計）
        })

    foreign = next(r for r in results if r["investor_type"] == "foreign")
    gross = foreign["buy_amount"] + foreign["sell_amount"]
    lo, hi = FOREIGN_GROSS_OKU_RANGE
    if not lo <= gross <= hi:
        raise ValueError(
            f"海外投資家の売買合計 {gross:,.0f}億円 が想定範囲外です。単位（千円）が変わった可能性があります"
        )

    for r in results:
        logger.info(f"[現物v3] {r['investor_type']:12s}: 買い={r['buy_amount']:>10,.0f}億 "
                    f"売り={r['sell_amount']:>10,.0f}億 差引={r['net_amount']:>+9,.0f}億")
    logger.info(f"[現物v3] 二市場・金額 行={row} / JPX週コード={week_code} / week={week_date}")
    return results


def _is_old_format(filepath) -> bool:
    """旧形式（市場ごとのシートがあり 'Tokyo & Nagoya' シートを持つ）かを中身で判定する。
    拡張子では判定しない（一時ファイルの拡張子が実体と違うことがあるため）。"""
    # with で閉じる（開いたままだと Windows で呼び出し側が一時ファイルを消せない）
    with pd.ExcelFile(filepath) as xls:
        return OLD_FORMAT_SHEET in xls.sheet_names


def parse_spot_xls(filepath, week_date, sheet_name=OLD_FORMAT_SHEET):
    """
    JPX現物XLSを読み込んで投資家別売買を返す。新旧どちらの形式も受け付ける。

    列定義（旧形式・Tokyo & Nagoya シート）:
      col4: TSE Prime のみの金額（千円）← 使用しない
      col8: Tokyo & Nagoya（二市場合計）の金額（千円）← 使用する
      単位変換: 千円 ÷ 100,000 = 億円

    Parameters
    ----------
    filepath   : str  JPX現物XLS/XLSXのパス
    week_date  : str  集計週末日 (YYYY-MM-DD)
    sheet_name : str  旧形式で読み取るシート名（デフォルト: Tokyo & Nagoya）

    Returns
    -------
    list of dict  weekly_spotテーブル挿入用データ
    """
    if not _is_old_format(filepath):
        return parse_spot_xlsx_v3(filepath, week_date)

    df = pd.read_excel(filepath, sheet_name=sheet_name, header=None)
    results = []

    for inv_key, (sell_row, buy_row) in INVESTOR_ROWS.items():
        try:
            sell = float(str(df.iloc[sell_row, 8]).replace(",", "").replace("NaN", "0"))
            buy  = float(str(df.iloc[buy_row,  8]).replace(",", "").replace("NaN", "0"))
            net      = (buy - sell) / 1e5   # 千円 → 億円
            buy_oku  = buy  / 1e5
            sell_oku = sell / 1e5
            results.append({
                "week_date":     week_date,
                "investor_type": inv_key,
                "buy_amount":    round(buy_oku,  2),
                "sell_amount":   round(sell_oku, 2),
                "net_amount":    round(net,      2),
                "market":        "prime",
            })
            print(f"{inv_key:12s}: 買い={buy_oku:>8,.0f}億 売り={sell_oku:>8,.0f}億 差引={net:>+8,.0f}億")
        except Exception as e:
            print(f"{inv_key}: エラー {e}")

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    filepath  = sys.argv[1] if len(sys.argv) > 1 else "stock_val_1_260304.xls"
    week_date = sys.argv[2] if len(sys.argv) > 2 else "2026-03-27"
    parse_spot_xls(filepath, week_date)
