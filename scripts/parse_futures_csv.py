import pandas as pd
import sys

# ======================================
# 先物CSVパーサー v3.0
# 修正日: 2026-04-23
# 修正点:
#   JPXが2026年4月頃にCSVフォーマットを変更。
#   旧: ヘッダーなし、1行に枚数・金額が混在（多列）
#   新: ヘッダーあり12列、枚数行(type=1)と金額行(type=2)が別行
#
#   列マッピング（新フォーマット）:
#     col0: 商品コード
#     col5: 投資家コード
#     col6: 量・値区分 (1=枚数, 2=金額)
#     col7: 売 Sales (gross)
#     col8: 売-差引 Balance (売り越し=負値)
#     col9: 買 Purchases (gross)
#     col10: 買-差引 Balance (買い越し=正値)
#
#   投資家コード変更:
#     旧10→新11 (dealer/自己)
#     旧50→新51 (individual/個人)
#     その他 21/22/23/24/31/32/33/41/60 は変更なし
#
#   金額単位: 旧=千円/百円単位（乗数必要） → 新=円単位（乗数不要）
# ======================================

# 商品コード → テーブル名  ※新フォーマットは金額が円単位のため乗数は常に1
FUTURES_CODES = {
    301: "nikkei225_large",
    313: "nikkei225_mini",
    314: "topix_large",
    316: "topix_mini",
}

# 新フォーマットの投資家コードマッピング
INVESTOR_CODES = {
    11: "dealer",             # 自己（証券会社）
    21: "insurance",          # 生保損保
    22: "city_regional_bank", # 都銀地銀
    23: "trust_bank",         # 信託銀行
    24: "other_financial",    # その他金融機関
    31: "investment_trust",   # 投資信託
    32: "corporate",          # 事業法人
    33: "other_institution",  # その他法人
    41: "securities",         # 証券会社
    51: "individual",         # 個人計
    60: "foreign",            # 海外投資家計
}


def parse_futures_csv(filepath, week_date):
    """
    JPX先物CSVを読み込んで投資家別ポジションを返す。

    新フォーマット（2026年4月〜）対応。
    各投資家×商品コードにつき枚数行(type=1)と金額行(type=2)の2行セット。
    net_lots / net_amount_oku = col8 + col10 で算出。
    """
    df = pd.read_csv(filepath, header=0)

    # 列インデックスで参照（ヘッダー名が文字化けする環境でも動作する）
    COL_PROD  = df.columns[0]   # 商品コード
    COL_INV   = df.columns[5]   # 投資家コード
    COL_TYPE  = df.columns[6]   # 量・値区分
    COL_SELL  = df.columns[7]   # 売 gross
    COL_SNET  = df.columns[8]   # 売-差引
    COL_BUY   = df.columns[9]   # 買 gross
    COL_BNET  = df.columns[10]  # 買-差引

    results = []

    for prod_code, futures_type in FUTURES_CODES.items():
        prod_df = df[df[COL_PROD] == prod_code]
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
                net_yen = float(ra[COL_SNET]) + float(ra[COL_BNET])
                net_oku = round(net_yen / 1e8, 2)
            else:
                net_oku = 0.0

            results.append({
                "week_date":      week_date,
                "investor_type":  inv_key,
                "futures_type":   futures_type,
                "short_lots":     short_lots,
                "long_lots":      long_lots,
                "net_lots":       net_lots,
                "index_close":    0.0,
                "net_amount_oku": net_oku,
                "source_url":     filepath,
            })

            direction = "買越" if net_lots > 0 else "売越"
            print(
                f"{futures_type:20s} | {inv_key:18s} | "
                f"売={short_lots:>10,}枚 | 買={long_lots:>10,}枚 | "
                f"差引={net_lots:>+10,}枚 | {net_oku:>+10.1f}億 ({direction})"
            )

    return results


if __name__ == "__main__":
    filepath  = sys.argv[1] if len(sys.argv) > 1 else "Tousi_DV_W_20260413_20260417.csv"
    week_date = sys.argv[2] if len(sys.argv) > 2 else "2026-04-17"

    print(f"\n=== JPX先物 投資家別売買動向 / {week_date} ===\n")
    data = parse_futures_csv(filepath, week_date)
    print(f"\n合計 {len(data)} レコード取得完了")
