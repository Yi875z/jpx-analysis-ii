# JPX ダッシュボード 引き継ぎ書
作成日: 2026-04-13（2026-04-12版を更新）

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

## 2026-04-13 実施した修正

### 1. KPIカード数値の色（ライトモード）✅ 解決
**問題:** 外国人・信託銀行・個人の数値が緑/赤で表示されなかった。

**原因:** inline style の `color:X !important` が、Streamlit の `.block-container { color: !important }` 継承チェーンに負けるケースがあった。

**解決策（`dashboard/app.py`）:**
- inline color を削除し、`.kpi-pos` / `.kpi-neg` クラスに置き換え
- KPI カードレンダリング前に別の `st.markdown()` でクラス CSS を注入
- 複合セレクター `[data-testid="stMarkdownContainer"] .kpi-pos` で高特異度を確保

```python
st.markdown("""
<style>
.kpi-pos, [data-testid="stMarkdownContainer"] .kpi-pos,
.block-container [data-testid="stMarkdownContainer"] .kpi-pos {
    color: #2dc653 !important;
}
.kpi-neg, [data-testid="stMarkdownContainer"] .kpi-neg,
.block-container [data-testid="stMarkdownContainer"] .kpi-neg {
    color: #e63946 !important;
}
</style>
""", unsafe_allow_html=True)
```

### 2. サイドバーの暗色残留 ✅ 解決
**問題:** ライトモードでサイドバーの背景が暗く、ナビゲーションテキストが白文字で見えなかった。

**解決策（`dashboard/components/theme.py` ライトモード CSS）:**
- `section[data-testid="stSidebar"] div` を明示的にターゲット
- `[data-testid="stSidebarNav"]` とその子要素（a, span, li）を白背景・暗色テキストに設定

### 3. ツインエンジンヒートマップの黒背景 ✅ 解決
**問題:** `3_合算分析.py` のヒートマップで OFF セル色が `#1a1a2e`（ダーク色）にハードコードされていた。

**解決策（`dashboard/pages/3_合算分析.py`）:**
```python
_t2 = get_theme()
off_color = _t2["bg2"]   # ライト=#ffffff / ダーク=#1a1a2e
colorscale=[[0, off_color], [1, "#2dc653"]],
```

### 4. ウィジェット・ドロップダウンの暗色残留 ✅ 解決
**問題:** 投資家フィルターの選択タグ・検索結果ポップオーバーが暗い背景のままだった。

**解決策（`dashboard/components/theme.py` ライトモード CSS）:**
- `[data-baseweb="tag"]` の背景色を明示設定
- `li[role="option"]` / `body [data-baseweb="menu"]` でポータル描画のポップオーバーもカバー
- ヘッダーバー（`header[data-testid="stHeader"]`）の背景も白に設定

---

## CSS 設計原則（重要・次回も守ること）

1. **`[stMarkdownContainer] *` ワイルドカード禁止** — KPI カード等の inline-styled div を上書きする
2. **KPI カード色は CSS クラスで管理** — `.kpi-pos` / `.kpi-neg` を別 `st.markdown()` で先に注入
3. **`config.toml` は `base="light"`** — ライトモードは Streamlit ネイティブに委ね、ダークモードだけ CSS 上書き
4. **ポップオーバーは `body [data-baseweb="..."]` で対応** — portal 描画のため通常の ancestor セレクターでは届かない
5. **Plotly のハードコード色は `get_theme()` で動的に切り替え** — カラースケール等は `t["bg2"]` 等を参照

---

## 主要コンポーネント解説

### data_loader.py
Supabase の max-rows=1000 制限を突破するページネーションループ実装済み。

接続設定:
- `.env` ファイルパス: `config/.env`
- 使用キー: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`（service_role キーを使用）

### charts.py
投資家色の定数が2種類ある:

- `COLORS["外国人"]` → `#29b6f6`（折れ線グラフ用）
- `INV_BAR_COLORS["外国人"]` → `{"pos": "#29b6f6", "neg": "#0277bd"}`（棒グラフ用）

5投資家の hue 設計:
- 外国人: 青（`#29b6f6` / `#0277bd`）
- 信託銀行: 橙（`#ffa726` / `#bf360c`）
- 個人: 赤（`#ef5350` / `#b71c1c`）
- 事業法人: 緑（`#66bb6a` / `#1b5e20`）
- 自己: 紫（`#ce93d8` / `#6a1b9a`）

### theme.py
`render_theme_toggle()` → サイドバーにボタン表示 + `_inject_css()` 呼び出し。
`plot_layout(**kwargs)` → Plotly レイアウトのテーマ対応 deep-merge ヘルパー。
`get_theme()` → `st.session_state["theme_mode"]`（デフォルト "light"）を返す。

### 4_Zスコア.py
`weekly_stats` テーブルのZスコアが信頼できないため、`weekly_spot`/`weekly_futures` から毎回動的に rolling 計算する。
**現在は現物のみ。先物Zスコアは未実装（次回課題）。**

---

## 今後の拡張候補（優先順）

### 高優先度
1. **先物Zスコアの追加（`4_Zスコア.py`）**
   - `weekly_futures` から `net_lots`（枚数）と `net_amount_oku`（億円）を rolling 計算
   - 外国人の先物Zスコアは相場先行指標として有用
   - 実装は現物と同じ rolling 計算なので難しくない
   - 表示案: 現物/先物タブ切り替え or サイドバーのラジオボタンで切り替え

### 中優先度
2. **ライトモードでの Plotly 凡例テキスト色改善**（現在 gray 気味）
3. **週次データ取得後の自動ダッシュボード更新**（n8n 連携）

### 低優先度
4. **スマホ対応**（Streamlit layout 調整）

---

## DB テーブル構造（参考）

### weekly_spot
| カラム | 内容 |
|--------|------|
| week_date | 集計週末日 |
| investor_type | foreign/trust_bank/inv_trust/individual/corporate/dealer |
| net_amount | 現物 NET（億円） |
| buy_amount | 買い越し額 |
| sell_amount | 売り越し額 |

### weekly_futures
| カラム | 内容 |
|--------|------|
| week_date | 集計週末日 |
| investor_type | foreign/trust_bank/individual/corporate/dealer |
| futures_type | nikkei225_large/topix_large |
| long_lots / short_lots / net_lots | 枚数 |
| net_amount_oku | 億円換算 |

### weekly_combined（ビューまたはテーブル）
| カラム | 内容 |
|--------|------|
| week_date | 集計週末日 |
| spot_net | 現物 NET |
| futures_net_oku | 先物 NET（億円） |
| combined_net | 合算 NET |
| is_twin_engine | ツインエンジン発動フラグ |

---

## よくある操作

- **キャッシュ更新**: サイドバーの「キャッシュ更新」ボタン or Streamlit 再起動
- **表示期間変更**: 各ページのサイドバー「表示期間」ラジオボタン
- **新しい週のデータ反映**: `python main.py` 実行後、「キャッシュ更新」クリック
