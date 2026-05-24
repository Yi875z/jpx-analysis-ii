"""
scripts/parse_options_csv.py
============================
JPXの「投資部門別売買状況」CSV（先物・オプション共通）から
日経225オプション および 日経225ミニオプション のコール・プット別の
投資家別売買データを抽出する。

商品コード対応（CSV登場順 == PDFページ順 で逆引きにより同定）:
  303 = 日経225オプション プット      (Nikkei 225 Options - Put)
  304 = 日経225オプション コール      (Nikkei 225 Options - Call)
  332 = 日経225ミニオプション プット  (Nikkei 225 mini Options - Put)
  333 = 日経225ミニオプション コール  (Nikkei 225 mini Options - Call)

行構造（既存 parse_futures_csv と同じ）:
  各投資家×商品コードにつき 枚数行(type=1) と 金額行(type=2) の2行セット
  col8 (売-差引) + col10 (買-差引) で net を計算
"""

from __future__ import annotations

import logging
import sys

import pandas as pd

logger = logging.getLogger(__name__)

# 商品コード → 内部キー
OPTIONS_CODES: dict[int, str] = {
    303: "nikkei225_put",
    304: "nikkei225_call",
    332: "nikkei225_mini_put",
    333: "nikkei225_mini_call",
}

# 投資家コード（parse_futures_csv.py と同じ）
INVESTOR_CODES: dict[int, str] = {
    11: "dealer",             # 自己（証券会社）
    21: "insurance",
    22: "city_regional_bank",
    23: "trust_bank",
    24: "other_financial",
    31: "investment_trust",   # 投資信託
    32: "corporate",          # 事業法人
    33: "other_institution",
    41: "securities",
    51: "individual",         # 個人
    60: "foreign",            # 海外投資家
}


def parse_options_csv(filepath: str, week_date: str, source_url: str | None = None) -> list[dict]:
    """JPX オプションCSV（投資部門別）をパースして投資家別レコードを返す。

    Returns: list of dicts with keys matching weekly_options schema.
    """
    df = pd.read_csv(filepath, header=0)

    COL_PROD = df.columns[0]    # 帳票種別 / 商品コード
    COL_INV  = df.columns[5]    # 投資部門コード
    COL_TYPE = df.columns[6]    # 数量金額区分 (1=枚数, 2=金額円)
    COL_SELL = df.columns[7]    # 売 (gross)
    COL_SNET = df.columns[8]    # 売-差引 (売り越し=負)
    COL_BUY  = df.columns[9]    # 買 (gross)
    COL_BNET = df.columns[10]   # 買-差引 (買い越し=正)

    src = source_url or filepath
    results: list[dict] = []

    for prod_code, option_type in OPTIONS_CODES.items():
        prod_df = df[df[COL_PROD] == prod_code]
        if prod_df.empty:
            logger.warning(f"[options] code {prod_code} ({option_type}) がCSVに存在しません")
            continue

        lots_df = prod_df[prod_df[COL_TYPE] == 1]
        amt_df  = prod_df[prod_df[COL_TYPE] == 2]

        for inv_code, inv_key in INVESTOR_CODES.items():
            lots_row = lots_df[lots_df[COL_INV] == inv_code]
            if lots_row.empty:
                continue
            r = lots_row.iloc[0]
            short_lots = int(r[COL_SELL])
            long_lots  = int(r[COL_BUY])
            net_lots   = int(r[COL_SNET]) + int(r[COL_BNET])

            amt_row = amt_df[amt_df[COL_INV] == inv_code]
            if not amt_row.empty:
                ra = amt_row.iloc[0]
                short_amount = int(ra[COL_SELL])
                long_amount  = int(ra[COL_BUY])
                net_yen      = float(ra[COL_SNET]) + float(ra[COL_BNET])
                net_oku      = round(net_yen / 1e8, 2)
            else:
                short_amount = long_amount = 0
                net_oku = 0.0

            results.append({
                "week_date":      week_date,
                "investor_type":  inv_key,
                "option_type":    option_type,
                "long_lots":      long_lots,
                "short_lots":     short_lots,
                "net_lots":       net_lots,
                "long_amount":    long_amount,
                "short_amount":   short_amount,
                "net_amount_oku": net_oku,
                "source_url":     src,
            })

    return results


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    filepath  = sys.argv[1] if len(sys.argv) > 1 else "Tousi_DV_W_20260511_20260515.csv"
    week_date = sys.argv[2] if len(sys.argv) > 2 else "2026-05-15"

    rows = parse_options_csv(filepath, week_date)
    print(f"\n=== JPX オプション 投資家別売買 / {week_date} ===\n")
    for r in rows:
        direction = "買越" if r["net_lots"] > 0 else "売越" if r["net_lots"] < 0 else "中立"
        print(
            f"{r['option_type']:25s} | {r['investor_type']:18s} | "
            f"売={r['short_lots']:>10,}枚 | 買={r['long_lots']:>10,}枚 | "
            f"net={r['net_lots']:>+10,}枚 | {r['net_amount_oku']:>+10.1f}億 ({direction})"
        )
    print(f"\n合計 {len(rows)} レコード")
