# Graph Report - jpx-analysis  (2026-05-08)

## Corpus Check
- 34 files · ~62,996 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 221 nodes · 292 edges · 21 communities detected
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 10 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 28|Community 28]]

## God Nodes (most connected - your core abstractions)
1. `get_client()` - 16 edges
2. `_fetch()` - 8 edges
3. `fetch_all()` - 8 edges
4. `_build_data_table()` - 7 edges
5. `LinkParser` - 7 edges
6. `_write_spot_sheet()` - 7 edges
7. `build_excel()` - 7 edges
8. `Handler` - 6 edges
9. `main()` - 6 edges
10. `main()` - 5 edges

## Surprising Connections (you probably didn't know these)
- `save_futures()` --calls--> `parse_futures_csv()`  [INFERRED]
  save_futures_to_db.py → scripts\parse_futures_csv.py
- `get_weekly_spot()` --calls--> `_compute_zscores()`  [INFERRED]
  dashboard\components\data_loader.py → dashboard\pages\4_Zスコア.py
- `get_weekly_futures()` --calls--> `_compute_zscores()`  [INFERRED]
  dashboard\components\data_loader.py → dashboard\pages\4_Zスコア.py
- `plot_layout()` --calls--> `_render_futures_tab()`  [INFERRED]
  dashboard\components\theme.py → dashboard\pages\2_先物フロー.py
- `LinkParser` --calls--> `fetch_spot_data()`  [INFERRED]
  scripts\backfill_jpx.py → skills\jpx-investor-data\scripts\fetch_jpx.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.11
Nodes (21): save_futures_to_db.py ===================== JPX先物CSVをパースしてSupabaseのweekly_future, 先物データをパースしてSupabaseに保存する。, save_futures(), CsvLinkParser, _download_to_tempfile(), fetch_all(), _find_col(), _get_csv_links() (+13 more)

### Community 1 - "Community 1"
Cohesion: 0.14
Nodes (21): build_all_years(), build_excel(), _calc_rolling_zscores(), _header_style(), _make_chart_image(), _make_comparison_image(), _make_zscore_image(), scripts/build_excel.py Supabase蓄積データからExcel累積ファイルを生成する (+13 more)

### Community 2 - "Community 2"
Cohesion: 0.17
Nodes (20): fetch_combined_history(), fetch_futures_history(), fetch_latest_week(), fetch_monthly_summary(), fetch_spot_history(), fetch_stats_history(), fetch_week_futures(), fetch_week_spot() (+12 more)

### Community 3 - "Community 3"
Cohesion: 0.15
Nodes (15): HTMLParser, _collect_links(), _get_done_dates(), LinkParser, main(), _parse_futures_info(), _parse_spot_key(), scripts/backfill_jpx.py JPXアーカイブから過去データを一括取得してSupabaseに投入するスクリプト。  使い方:   # 2025 (+7 more)

### Community 4 - "Community 4"
Cohesion: 0.18
Nodes (16): _build_data_table(), _build_futures_breakdown(), _build_monthly_data_table(), _build_spot_futures_detail(), _fmt_diff(), _fmt_net(), generate_monthly_report(), generate_weekly_report() (+8 more)

### Community 5 - "Community 5"
Cohesion: 0.21
Nodes (13): _client(), _fetch(), get_latest_week_date(), get_monthly_summary(), get_weekly_combined(), get_weekly_futures(), get_weekly_spot(), get_weekly_stats() (+5 more)

### Community 6 - "Community 6"
Cohesion: 0.33
Nodes (10): _get_week_date(), main(), main.py JPX投資主体別売買動向 自動分析システム メインエントリーポイント（手動実行・n8nから呼び出し共通）  使い方:   python main, 集計基準日（週末の金曜日）を返す。     JPXは木曜日に前週（月〜金）のデータを公開するため、     木曜実行時は翌日（金曜）を基準日とする。, run_monthly(), run_report_only(), run_weekly(), _save_excel() (+2 more)

### Community 7 - "Community 7"
Cohesion: 0.22
Nodes (9): get_theme(), _inject_css(), plot_layout(), テーマ管理モジュール（ダーク / ライト切り替え） config.toml は base="light" を前提とする。 - ライトモード: Streamlit, Plotlyグラフのlayout共通設定をテーマに合わせて返す（ネストdict深合成）, サイドバーにダーク/ライト切り替えボタンを表示し、CSSを注入する, render_theme_toggle(), 先物フロー分析ページ 日経225先物 / TOPIX先物 切り替えタブ NET（ロット）推移 + NET（億円）推移 (+1 more)

### Community 8 - "Community 8"
Cohesion: 0.25
Nodes (9): build_analysis_context(), build_monthly(), build_stats(), calc_ma(), calc_zscore(), scripts/analyze_jpx.py Supabase蓄積データからZスコア・合算・月次集計を計算する, 指定年月（YYYY-MM）の週次データを集計して月次サマリーを生成, レポート生成AIエージェントに渡す分析コンテキストを構築する (+1 more)

### Community 9 - "Community 9"
Cohesion: 0.31
Nodes (9): bar_chart(), combined_bar_line(), _hover_pn(), _hover_solid(), _label(), line_chart(), グラフ共通関数 Plotly図表の生成ユーティリティ, 正負で背景色を変えるhoverlabel設定 (+1 more)

### Community 10 - "Community 10"
Cohesion: 0.36
Nodes (9): build_excel(), build_markdown(), build_pdf(), fmt_diff(), fmt_net(), load_analysis(), main(), Excelファイルを生成（openpyxl使用） (+1 more)

### Community 11 - "Community 11"
Cohesion: 0.36
Nodes (8): analyze_spot(), build_summary_table(), calc_net(), flexible_column_map(), main(), Shift-JIS/UTF-8を両方試してCSV読み込み, カラム名を柔軟にマッピング。見つからないキーはNoneを返す, try_read_csv()

### Community 12 - "Community 12"
Cohesion: 0.32
Nodes (3): BaseHTTPRequestHandler, Handler, api_server.py n8n(Docker)からWindows上のPythonスクリプトを実行するためのHTTPサーバー。 ポート8765で待ち受け、n8

### Community 13 - "Community 13"
Cohesion: 0.33
Nodes (2): format_oku(), 億円表示フォーマット（例: +1,234億）

### Community 14 - "Community 14"
Cohesion: 0.67
Nodes (1): 月次集計ページ - 月次フロー棒グラフ（現物・先物・合算） - 投資家別月次ヒートマップ - 直近12ヶ月の推移テーブル（色付きセル）

### Community 15 - "Community 15"
Cohesion: 0.67
Nodes (1): scripts/extract_report_summary.py n8nワークフローから呼び出して最新レポートのエグゼクティブサマリーを stdout に出力

### Community 16 - "Community 16"
Cohesion: 1.0
Nodes (1): JPX投資主体別売買動向ダッシュボード トップ画面: 最新週KPI・ツインエンジン判定・4週トレンドグラフ

### Community 17 - "Community 17"
Cohesion: 1.0
Nodes (1): 現物フロー分析ページ 投資家別NET推移（折れ線）+ 買い越し/売り越し（棒グラフ）

### Community 18 - "Community 18"
Cohesion: 1.0
Nodes (1): 合算分析ページ - 現物 vs 先物 方向一致/乖離チャート（2軸） - ツインエンジン発動履歴（ヒートマップ） - 外国人 現物+先物合算 累積フロー（棒+折

### Community 19 - "Community 19"
Cohesion: 1.0
Nodes (1): Supabase スキーマ確認スクリプト information_schema からテーブル名・カラム名・型を一覧表示する

### Community 28 - "Community 28"
Cohesion: 1.0
Nodes (1): Claude APIを呼び出して週次レポートのMarkdownを生成する      Parameters     ----------     week_dat

## Knowledge Gaps
- **62 isolated node(s):** `api_server.py n8n(Docker)からWindows上のPythonスクリプトを実行するためのHTTPサーバー。 ポート8765で待ち受け、n8`, `main.py JPX投資主体別売買動向 自動分析システム メインエントリーポイント（手動実行・n8nから呼び出し共通）  使い方:   python main`, `集計基準日（週末の金曜日）を返す。     JPXは木曜日に前週（月〜金）のデータを公開するため、     木曜実行時は翌日（金曜）を基準日とする。`, `save_futures_to_db.py ===================== JPX先物CSVをパースしてSupabaseのweekly_future`, `先物データをパースしてSupabaseに保存する。` (+57 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 13`** (6 nodes): `format_oku()`, `latest_net()`, `prev_net()`, `億円表示フォーマット（例: +1,234億）`, `wow_delta()`, `metrics.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 14`** (3 nodes): `5_月次集計.py`, `_color_cell()`, `月次集計ページ - 月次フロー棒グラフ（現物・先物・合算） - 投資家別月次ヒートマップ - 直近12ヶ月の推移テーブル（色付きセル）`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 15`** (3 nodes): `main()`, `extract_report_summary.py`, `scripts/extract_report_summary.py n8nワークフローから呼び出して最新レポートのエグゼクティブサマリーを stdout に出力`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 16`** (2 nodes): `app.py`, `JPX投資主体別売買動向ダッシュボード トップ画面: 最新週KPI・ツインエンジン判定・4週トレンドグラフ`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 17`** (2 nodes): `1_現物フロー.py`, `現物フロー分析ページ 投資家別NET推移（折れ線）+ 買い越し/売り越し（棒グラフ）`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 18`** (2 nodes): `3_合算分析.py`, `合算分析ページ - 現物 vs 先物 方向一致/乖離チャート（2軸） - ツインエンジン発動履歴（ヒートマップ） - 外国人 現物+先物合算 累積フロー（棒+折`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 19`** (2 nodes): `show_schema.py`, `Supabase スキーマ確認スクリプト information_schema からテーブル名・カラム名・型を一覧表示する`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 28`** (1 nodes): `Claude APIを呼び出して週次レポートのMarkdownを生成する      Parameters     ----------     week_dat`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CsvLinkParser` connect `Community 0` to `Community 3`?**
  _High betweenness centrality (0.023) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `fetch_all()` (e.g. with `parse_spot_xls()` and `parse_futures_csv()`) actually correct?**
  _`fetch_all()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `LinkParser` (e.g. with `fetch_spot_data()` and `fetch_futures_data()`) actually correct?**
  _`LinkParser` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `api_server.py n8n(Docker)からWindows上のPythonスクリプトを実行するためのHTTPサーバー。 ポート8765で待ち受け、n8`, `main.py JPX投資主体別売買動向 自動分析システム メインエントリーポイント（手動実行・n8nから呼び出し共通）  使い方:   python main`, `集計基準日（週末の金曜日）を返す。     JPXは木曜日に前週（月〜金）のデータを公開するため、     木曜実行時は翌日（金曜）を基準日とする。` to the rest of the system?**
  _62 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.11 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.14 - nodes in this community are weakly interconnected._