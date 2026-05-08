import pandas as pd
import sys

# ======================================
# 現物XLSパーサー v2.0
# 修正日: 2026-04-06
# 修正点:
#   ① シート名を 'Tokyo & Nagoya' に変更（二市場合計が正式対象）
#   ② 読み取り列を col4 → col8 に変更（Tokyo & Nagoya の金額列）
#   ③ 単位変換を /1e8 → /1e5 に修正（千円 → 億円）
#   ④ "trust" (rows37-38) は投資信託（inv_trust）に訂正
#   ⑤ 信託銀行 (trust_bank) を rows57-58 から追加
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


def parse_spot_xls(filepath, week_date, sheet_name="Tokyo & Nagoya"):
    """
    JPX現物XLSを読み込んで投資家別売買を返す。

    列定義（Tokyo & Nagoya シート）:
      col4: TSE Prime のみの金額（千円）← 使用しない
      col8: Tokyo & Nagoya（二市場合計）の金額（千円）← 使用する
      単位変換: 千円 ÷ 100,000 = 億円

    Parameters
    ----------
    filepath   : str  JPX現物XLSのパス
    week_date  : str  集計週末日 (YYYY-MM-DD)
    sheet_name : str  読み取るシート名（デフォルト: Tokyo & Nagoya）

    Returns
    -------
    list of dict  weekly_spotテーブル挿入用データ
    """
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
    filepath  = sys.argv[1] if len(sys.argv) > 1 else "stock_val_1_260304.xls"
    week_date = sys.argv[2] if len(sys.argv) > 2 else "2026-03-27"
    parse_spot_xls(filepath, week_date)
