# JPX ダッシュボード 引き継ぎ書
作成日: 2026-04-12

---

## 概要

Streamlit を使った JPX 投資主体別売買動向ダッシュボード。
Supabase の `weekly_spot`・`weekly_futures`・`weekly_combined` テーブルを読み込み可視化する。

**起動コマンド:**
```powershell
cd C:\CarSol\jpx-analysis
streamlit run dashboard/app.py
# → http://localhost:8501
```

---

## ファイル構成

```
dashboard/
├── app.py                    トップ画面
├── components/
│   ├── data_loader.py        Supabase データ取得（ページネーション対応）
│   ├── charts.py             色定数・グラフ共通関数
│   ├── metrics.py            KPI 計算関数
│   └── theme.py              ダーク/ライトテーマ切り替え
└── pages/
    ├── 1_現物フロー.py       投資家別 NET 推移（折れ線+棒）
    ├── 2_先物フロー.py       日経225/TOPIX 先物 NET（枚・億円）
    ├── 3_合算分析.py         現物vs先物 乖離・ツインエンジン・累積フロー
    ├── 4_Zスコア.py          Zスコア ヒートマップ・26w vs 52w 比較・4週MA
    └── 5_月次集計.py         月次フロー・ヒートマップ・推移テーブル
.streamlit/
    └── config.toml           base = "light"
```

---

## 主要コンポーネント解説

### data_loader.py
Supabase の max-rows=1000 制限を突破するページネーションループ実装済み。

```python
# _fetch() の核心部分
while True:
    resp = q.range(offset, offset + 999).execute()
    rows = resp.data or []
    all_rows.extend(rows)
    if len(rows) < 1000:
        break
    offset += 1000
```

接続設定:
- `.env` ファイルパス: `config/.env`
- 使用キー: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`（service_role キーを使用）

### charts.py
投資家色の定数が2種類ある:

| 定数 | 用途 | 色 |
|------|------|-----|
| `COLORS["外国人"]` | 折れ線グラフ | `#29b6f6`（水色） |
| `INV_BAR_COLORS["外国人"]` | 棒グラフ pos/neg | `{"pos": "#29b6f6", "neg": "#0277bd"}` |

5投資家の hue 設計:
- 外国人: 青（`#29b6f6` / `#0277bd`）
- 信託銀行: 橙（`#ffa726` / `#bf360c`）
- 個人: 赤（`#ef5350` / `#b71c1c`）
- 事業法人: 緑（`#66bb6a` / `#1b5e20`）
- 自己: 紫（`#ce93d8` / `#6a1b9a`）

### theme.py
`config.toml` を `base="light"` で運用する設計。

- **ライトモード**: Streamlit ネイティブ light theme + `.stApp { color: #1a1a2a !important }` でダーク残留 CSS をリセット
- **ダークモード**: 包括的 CSS 注入（ただし `[stMarkdownContainer] *` のワイルドカードは禁止）
- `plot_layout(**kwargs)`: Plotly チャートのテーマ対応レイアウト（ネスト dict 深合成対応）

**CSS 注意事項（重要）:**  
`[data-testid="stMarkdownContainer"] *` のワイルドカード + `!important` は使ってはいけない。
KPI カード等の inline-styled `<div>` の色が上書きされて白文字になる。

### 4_Zスコア.py
`weekly_stats` テーブルのZスコアが信頼できないため、このページは `weekly_spot`/`weekly_futures` から
**毎回動的に rolling 計算**する。

```python
grp["zscore_26w"] = (
    (grp["value"] - grp["value"].rolling(26, min_periods=10).mean())
    / grp["value"].rolling(26, min_periods=10).std()
)
```

---

## 未解決の問題（次回対応）

### KPI カード数値の色（ライトモード）
**症状:** ライトモードで +19,150億 などの数値が緑/赤にならず、暗色（テーマ色）になる場合がある。

**現在の実装 (`app.py`):**
```python
val_color = "#2dc653" if cur >= 0 else "#e63946"
st.markdown(f"""
  <div style="color:{val_color} !important;font-size:28px;...">
    {format_oku(cur)}
  </div>
""", unsafe_allow_html=True)
```

**根本原因の仮説:**  
ライトモード CSS の `.stApp { color: #1a1a2a !important }` が DOM 上で KPI カードの
inline style より後に来る場合、CSS 仕様上は inline `!important` が勝つはずだが、
Streamlit の DOM 差分更新タイミングにより意図通りに動かないことがある。

**次回検討案:**
1. `st.metric()` ネイティブコンポーネントに置換（デザインは変わるが確実）
2. CSS 変数（`--kpi-color: green`）を注入し、クラス `kpi-value` で参照する方式
3. 別の `st.markdown` 呼び出しで CSS のみ注入し、HTML 要素とは分離する

---

## DB テーブル構造（参考）

### weekly_spot
| カラム | 型 | 内容 |
|--------|-----|------|
| week_date | date | 集計週末日 |
| investor_type | text | foreign/trust_bank/inv_trust/individual/corporate/dealer |
| net_amount | numeric | 現物 NET（億円） |
| buy_amount | numeric | 買い越し額 |
| sell_amount | numeric | 売り越し額 |

### weekly_futures
| カラム | 型 | 内容 |
|--------|-----|------|
| week_date | date | 集計週末日 |
| investor_type | text | foreign/trust_bank/individual/corporate/dealer |
| futures_type | text | nikkei225_large/topix_large |
| long_lots | numeric | 買い建て枚数 |
| short_lots | numeric | 売り建て枚数 |
| net_lots | numeric | 差引き枚数 |
| net_amount_oku | numeric | 億円換算 |

### weekly_combined（ビューまたはテーブル）
| カラム | 型 | 内容 |
|--------|-----|------|
| week_date | date | 集計週末日 |
| investor_type | text | 投資家区分 |
| spot_net | numeric | 現物 NET |
| futures_net_oku | numeric | 先物 NET（億円） |
| combined_net | numeric | 合算 NET |
| is_twin_engine | boolean | ツインエンジン発動フラグ |

---

## よくある操作

### キャッシュをクリアしてデータを最新化
サイドバーの「キャッシュ更新」ボタンをクリック。または Streamlit を再起動。

### 表示期間を変更
各ページのサイドバー「表示期間」ラジオボタンで変更（4週/13週/26週/52週など）。

### 新しい週のデータが反映されない
バックエンドの `main.py` を実行して Supabase にデータを保存してから、
ダッシュボードで「キャッシュ更新」をクリック。

---

## 今後の拡張候補（優先順）
1. KPI カード色問題の根本解決（st.metric 移行 or CSS 変数アプローチ）
2. ライトモードでの Plotly チャートの凡例テキスト色（現在 gray）
3. 週次データ取得後の自動ダッシュボード更新（n8n 連携）
4. スマホ対応（Streamlit layout 調整）
