# JPX投資主体別売買動向 ダッシュボード開発指示書
# Claude Code (Cursor) 用

---

## プロジェクト概要

既存のJPX投資主体別売買動向分析システム（Supabase + Python + n8n）に、
Webブラウザで閲覧できるビジュアライズダッシュボードを追加開発する。

- **フレームワーク**: Streamlit
- **データソース**: Supabase（既存）
- **言語**: Python
- **配置場所**: `C:\CarSol\jpx-analysis\dashboard\`

---

## 既存DB構造（Supabase）

### テーブル一覧

```
weekly_spot       - 現物需給データ（メイン）
weekly_futures    - 先物需給データ（メイン）
weekly_combined   - 現物＋先物合算・ツインエンジン判定
weekly_stats      - Zスコア・移動平均・前週比統計
monthly_summary   - 月次集計
reports           - 生成済みレポート管理
fetch_logs        - データ取得ジョブログ
```

### 主要カラム

**weekly_spot**
```
week_date, investor_type, market,
buy_amount, sell_amount, net_amount
```

**weekly_futures**
```
week_date, investor_type, futures_type,
long_lots, short_lots, net_lots, net_amount_oku
※ カラム名は sell_lots/buy_lots ではなく long_lots/short_lots
```

**weekly_combined**
```
week_date, investor_type,
spot_net, futures_net_oku, combined_net, is_twin_engine
```

**weekly_stats**
```
week_date, investor_type,
zscore_26w, zscore_52w, ma4w, wow_change
```

**monthly_summary**
```
year_month, investor_type,
spot_net_sum, futures_net_sum, combined_net_sum
```

---

## 開発タスク

### STEP 1: 環境セットアップ

以下のファイルを `C:\CarSol\jpx-analysis\dashboard\` 配下に作成すること。

**必要パッケージのインストール:**
```bash
pip install streamlit plotly pandas supabase python-dotenv
```

**ディレクトリ構成:**
```
dashboard/
├── app.py              # メインアプリ
├── pages/
│   ├── 1_現物フロー.py
│   ├── 2_先物フロー.py
│   ├── 3_合算分析.py
│   ├── 4_Zスコア.py
│   └── 5_月次集計.py
├── components/
│   ├── data_loader.py  # Supabaseデータ取得
│   ├── charts.py       # グラフ共通関数
│   └── metrics.py      # KPI計算
└── .streamlit/
    └── config.toml     # テーマ設定
```

---

### STEP 2: Supabase接続設定

`components/data_loader.py` を作成:

- 既存の `.env` ファイルから `SUPABASE_URL` と `SUPABASE_KEY` を読み込む
- 既存プロジェクトの `.env` パスは `C:\CarSol\jpx-analysis\.env`
- 各テーブルのデータ取得関数を実装
- `@st.cache_data(ttl=3600)` でキャッシュ（1時間）

```python
# 実装すべき関数
def get_weekly_spot(weeks: int = 52) -> pd.DataFrame
def get_weekly_futures(weeks: int = 52) -> pd.DataFrame
def get_weekly_combined(weeks: int = 52) -> pd.DataFrame
def get_weekly_stats(weeks: int = 52) -> pd.DataFrame
def get_monthly_summary(months: int = 12) -> pd.DataFrame
def get_latest_week_date() -> str
```

---

### STEP 3: メイン画面（app.py）

**トップページの構成:**

```
┌─────────────────────────────────────────┐
│  📊 JPX投資主体別売買動向ダッシュボード   │
│  最新週: 2025-XX-XX（木曜日）             │
├──────────┬──────────┬────────────────────┤
│外国人NET  │信託銀行NET│個人NET             │
│ +1,234億 │ -567億   │ -890億             │
├──────────┴──────────┴────────────────────┤
│ ツインエンジン判定: 🟢 ON（外国人現物+先物）│
├─────────────────────────────────────────┤
│ 直近4週トレンド（折れ線グラフ）           │
└─────────────────────────────────────────┘
```

**実装要件:**
- 最新週のKPIカードを3列表示（外国人・信託銀行・個人）
- 前週比を矢印と色で表示（↑緑 / ↓赤）
- ツインエンジン判定（is_twin_engine）を目立つバッジで表示
- 直近4週の現物・先物合算NET推移グラフ

---

### STEP 4: 各ページ実装

#### pages/1_現物フロー.py

- **投資家別NET推移グラフ**（週次折れ線、複数投資家を色分け）
- **買い越し/売り越しの棒グラフ**（週次、プラス/マイナスで色分け）
- **表示期間選択**: 4週 / 13週 / 26週 / 52週
- **投資家フィルター**: 外国人・個人・信託銀行・事業法人・自己

#### pages/2_先物フロー.py

- **先物NET（ロット）推移グラフ**
- **先物NET（億円換算）推移グラフ**
- **日経225先物 / TOPIX先物 切り替えタブ**
- 表示期間・投資家フィルターは現物と同様

#### pages/3_合算分析.py

- **現物vs先物の方向一致/乖離チャート**（散布図または2軸グラフ）
- **ツインエンジン発動履歴**（週次カレンダーヒートマップ風）
- **外国人の現物+先物合算累積フロー**（棒グラフ+折れ線の複合）

#### pages/4_Zスコア.py

- **Zスコアヒートマップ**（投資家×週のヒートマップ）
  - 閾値: +2.0以上=赤（過熱）、-2.0以下=青（売られすぎ）、±1.0以内=グレー
- **26週Zスコア vs 52週Zスコア 比較**
- **4週移動平均トレンド**

#### pages/5_月次集計.py

- **月次フロー棒グラフ**（現物・先物・合算）
- **投資家別月次ヒートマップ**
- **直近12ヶ月の推移テーブル**（色付きセル）

---

### STEP 5: テーマ・スタイル設定

`.streamlit/config.toml`:

```toml
[theme]
primaryColor = "#1f4e79"
backgroundColor = "#0e1117"
secondaryBackgroundColor = "#1a1a2e"
textColor = "#ffffff"
font = "sans serif"

[server]
port = 8501
headless = true
```

**グラフカラーパレット（charts.py で定数定義）:**
```python
COLORS = {
    "外国人":   "#00b4d8",  # 青
    "信託銀行": "#f77f00",  # オレンジ
    "個人":     "#e63946",  # 赤
    "事業法人": "#2dc653",  # 緑
    "自己":     "#9b5de5",  # 紫
    "positive": "#2dc653",  # 買い越し=緑
    "negative": "#e63946",  # 売り越し=赤
}
```

---

### STEP 6: 起動スクリプト

`C:\CarSol\jpx-analysis\` 直下に `start_dashboard.bat` を作成:

```bat
@echo off
cd /d C:\CarSol\jpx-analysis
streamlit run dashboard/app.py
pause
```

---

## 実装上の注意事項

1. **既存コードを壊さない**: 既存の `scripts/` フォルダは変更しない
2. **環境変数**: 既存の `.env` をそのまま使用。新規キー追加不要
3. **カラム名**: `weekly_futures` は `long_lots` / `short_lots`（`sell_lots`/`buy_lots` ではない）
4. **エラーハンドリング**: Supabase接続失敗時はst.errorで分かりやすく表示
5. **データなし対応**: テーブルが空の場合もクラッシュしないこと
6. **日本語**: ラベル・凡例・軸名はすべて日本語
7. **レスポンシブ**: `use_container_width=True` をグラフに設定

---

## 動作確認手順

```bash
# 1. 依存パッケージ確認
pip install streamlit plotly pandas supabase python-dotenv

# 2. 起動
cd C:\CarSol\jpx-analysis
streamlit run dashboard/app.py

# 3. ブラウザで確認
# http://localhost:8501
```

---

## 優先順位

| 優先度 | タスク |
|--------|--------|
| 🔴 最優先 | STEP1〜3（環境・接続・トップ画面） |
| 🟡 次優先 | STEP4（現物・先物・合算ページ） |
| 🟢 後回し | Zスコアページ・月次集計ページ |

まずSTEP1〜3を完成させて動作確認してから、STEP4以降に進むこと。

---

## 完成イメージ

```
http://localhost:8501

サイドバー:
├── 🏠 ホーム（最新週サマリー）
├── 📈 現物フロー
├── 📉 先物フロー
├── ⚡ 合算分析
├── 📊 Zスコア
└── 📅 月次集計
```
