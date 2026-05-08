# JPX CSVカラム名マッピング

JPXのCSVは年度改訂でカラム名が変わることがある。
以下の別名リストを使ってflexibleにマッピングすること。

## 現物（東証プライム）

| 内部キー | 正式名称 | 別名（過去版） |
|---------|---------|--------------|
| week_date | 週（基準日） | 対象週, 週次 |
| foreign_buy | 海外投資家_買い付け | 外国人_買い, 外国人買い |
| foreign_sell | 海外投資家_売り付け | 外国人_売り, 外国人売り |
| individual_buy | 個人_買い付け | 個人投資家_買い |
| individual_sell | 個人_売り付け | 個人投資家_売り |
| trust_buy | 投信・信託銀行_買い付け | 信託銀行_買い, 投信_買い |
| trust_sell | 投信・信託銀行_売り付け | 信託銀行_売り |
| corporate_buy | 事業法人_買い付け | 法人_買い |
| corporate_sell | 事業法人_売り付け | 法人_売り |
| dealer_buy | 自己_買い付け | 証券会社自己_買い |
| dealer_sell | 自己_売り付け | 証券会社自己_売り |

## 先物（日経225・TOPIX先物）

| 内部キー | 正式名称 | 備考 |
|---------|---------|------|
| futures_type | 先物種別 | 日経225 / TOPIX等 |
| foreign_long | 海外投資家_買建 | 枚数 |
| foreign_short | 海外投資家_売建 | 枚数 |
| individual_long | 個人_買建 | |
| individual_short | 個人_売建 | |
| trust_long | 投信・信託銀行_買建 | |
| trust_short | 投信・信託銀行_売建 | |
| corporate_long | 事業法人_買建 | |
| corporate_short | 事業法人_売建 | |
| dealer_long | 自己_買建 | |
| dealer_short | 自己_売建 | |

## マッピング失敗時の対応

1. カラム名を小文字・スペース除去で再試行
2. それでも一致しない場合はユーザーに先頭5行を提示して確認
