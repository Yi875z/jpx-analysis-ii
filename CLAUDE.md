# JPX需給分析システム - Claude Code 作業指示書

## プロジェクト概要
JPX先物CSVデータをSupabaseに保存し、Claude APIで需給レポートを生成するシステム。
加えて Streamlit ダッシュボードで可視化（localhost:8501）。

## 現在の作業状態（2026-04-13更新）

### 完了済み（バックエンド）
- [x] `scripts/parse_futures_csv.py` — 投資家コード・列定義修正済み v1.1
- [x] `save_futures_to_db.py` — 先物データ保存スクリプト
- [x] `save_to_db.py` — 現物データ保存スクリプト
- [x] n8n自動化（毎週木曜20時）・api_server.py・Windowsスタートアップ登録済み
- [x] バックフィル完了（2025-04-04〜2026-04-03 / 54週）

### 完了済み（ダッシュボード）
- [x] `dashboard/app.py` — トップ画面（KPIカード・ツインエンジン・4週トレンド）
- [x] `dashboard/pages/1_現物フロー.py`
- [x] `dashboard/pages/2_先物フロー.py`
- [x] `dashboard/pages/3_合算分析.py`
- [x] `dashboard/pages/4_Zスコア.py`
- [x] `dashboard/pages/5_月次集計.py`
- [x] ダーク/ライトモード切り替えボタン
- [x] 投資家別バーチャートカラー（5色完全分離）
- [x] **KPIカード数値の色（ライトモード）** — `.kpi-pos`/`.kpi-neg` クラスで解決（2026-04-13）
- [x] **サイドバー・ウィジェット・ポップオーバーの暗色残留** — CSS強化で解決（2026-04-13）
- [x] **ツインエンジンヒートマップ黒背景** — colorscale を get_theme() で動的化（2026-04-13）

### 次回対応候補
- [ ] **先物Zスコアの追加**（`4_Zスコア.py`）: weekly_futures から net_lots/net_amount_oku の rolling 計算
  - 現在は現物Zスコアのみ。外国人の先物Zスコアは相場先行指標として有用。
- [ ] Plotly凡例テキスト色の改善（ライトモードで gray 気味）
- [ ] n8n連携による週次自動ダッシュボード更新

### CSS設計原則（必ず守ること）
- `[stMarkdownContainer] *` ワイルドカード禁止（KPI inline style を上書きする）
- KPIカード色は `.kpi-pos`/`.kpi-neg` クラスで管理（別 st.markdown で先に注入）
- ポップオーバーは `body [data-baseweb="..."]` で対応（portal 描画のため）
- Plotly ハードコード色は `get_theme()` で動的に切り替え

---

## ダッシュボード起動
```powershell
cd C:\CarSol\jpx-analysis
streamlit run dashboard/app.py
# → http://localhost:8501
```

## バックエンド実行コマンド（PowerShell）
```powershell
cd C:\CarSol\jpx-analysis

# 週次レポート再生成
python main.py --report-only --date YYYY-MM-DD

# 月次サマリー集計
python main.py --monthly YYYY-MM

# Excel全年再生成
python scripts/build_excel.py

# 過去データバックフィル
python scripts/backfill_jpx.py --from YYYY-MM-DD
```

---

## 重要な修正メモ（parse_futures_csv.py）

| 区分 | 旧コード（誤） | 正しいコード |
|------|------------|----------|
| 海外投資家 | 50 | **60** |
| 信託銀行 | 21 | **23** |
| 事業法人 | 22 | **32** |
| 個人 | 30 | 30（変更なし） |
| 自己 | 10 | 10（変更なし） |

---

## フォルダ構成

```
C:\CarSol\jpx-analysis\
├── .streamlit/config.toml       ← base="light"（ダッシュボードテーマ設定）
├── config/.env                  ← SUPABASE_URL / SUPABASE_KEY / ANTHROPIC_API_KEY
├── dashboard/                   ← Streamlitダッシュボード
│   ├── app.py
│   ├── components/
│   │   ├── data_loader.py       ← Supabase接続・1000行ページネーション対応
│   │   ├── charts.py            ← COLORS / INV_BAR_COLORS
│   │   ├── metrics.py
│   │   └── theme.py             ← ダーク/ライト切り替え
│   └── pages/
│       ├── 1_現物フロー.py
│       ├── 2_先物フロー.py
│       ├── 3_合算分析.py
│       ├── 4_Zスコア.py
│       └── 5_月次集計.py
├── scripts/
│   ├── parse_futures_csv.py     ← ★修正済み v1.1
│   └── parse_spot_xls.py
├── agents/
│   └── report_agent.py
├── save_to_db.py
├── save_futures_to_db.py
├── HANDOVER_20260412.md         ← バックエンド引き継ぎ書
└── HANDOVER_DASHBOARD_20260413.md ← ダッシュボード引き継ぎ書（最新）
```

---

## .env の形式

実値は `config/.env` を参照すること（URL・キーの実値をチャット・ドキュメントに書かない）。

```
SUPABASE_URL=（config/.env 参照）
SUPABASE_KEY=（config/.env 参照・サービスロールキー）
ANTHROPIC_API_KEY=（config/.env 参照）
```

---

## weekly_futures テーブルのカラム

| カラム | 型 | 内容 |
|--------|-----|------|
| week_date | date | 集計週末日 |
| investor_type | text | foreign/individual/trust_bank/corporate/dealer |
| futures_type | text | nikkei225_large/topix_large |
| long_lots | numeric | 買い建て枚数 |
| short_lots | numeric | 売り建て枚数 |
| net_lots | numeric | 差引き枚数（買い越し=正） |
| index_close | numeric | 終値 |
| net_amount_oku | numeric | 金額換算億円 |
| source_url | text | ソースCSVパス |

---

## エラー時の対処

### "SUPABASE_KEY が設定されていない"
→ Supabaseダッシュボード > Settings > API > `service_role` キーを .env に追加

### "weekly_futures テーブルが存在しない"
→ Supabaseダッシュボード > SQL Editor で db/schema.sql を再実行

### ダッシュボードでデータが古い・範囲が短い
→ サイドバーの「キャッシュ更新」ボタンをクリック
→ それでも直らない場合は Streamlit を再起動

### ダッシュボード Supabase 1000行制限
→ data_loader.py の `_fetch()` がページネーションループで対応済み

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
