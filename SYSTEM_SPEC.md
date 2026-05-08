# JPX投資主体別売買動向 自動分析システム 仕様書

作成日: 2026-04-14  
バージョン: 1.0

---

## 1. システム概要

JPX（日本取引所グループ）が毎週木曜日に公開する投資部門別売買状況データを自動取得・分析し、AI生成の需給レポートをメール配信するシステム。Streamlitダッシュボードで可視化も行う。

### システムの目的
- 外国人・信託銀行・個人など5区分の売買動向を週次で自動集計
- 現物・先物・合算のZスコアで需給の過熱/縮小を数値化
- Claude APIによるAI需給レポートを毎週自動生成・Gmail送信
- Streamlitダッシュボードでインタラクティブに可視化

### 対象データ
- **現物**: 東証プライム市場（週次・投資家別）
- **先物**: 日経225先物・TOPIX先物（週次・投資家別・枚数/億円）
- **集計期間**: 2025年4月〜現在（毎週木曜自動更新）

---

## 2. システム全体アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                      Windows 11 PC                          │
│                                                             │
│  ┌─────────────┐    HTTP     ┌──────────────────────────┐  │
│  │   Docker    │   :8765     │   Python バックエンド     │  │
│  │    n8n      │ ──────────► │   api_server.py          │  │
│  │  :5678      │             │   main.py                │  │
│  └─────────────┘             │   scripts/               │  │
│        │                     │   agents/                │  │
│        │ スケジュール         └────────────┬─────────────┘  │
│        │ (毎週木曜20時)                    │               │
│        │                                  │ データ読み書き  │
│  ┌─────▼─────────────────────────────────▼─────────────┐  │
│  │              Supabase（クラウドDB）                   │  │
│  │  weekly_spot / weekly_futures / weekly_combined      │  │
│  │  weekly_stats / monthly_summary / reports / logs     │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────┐   ┌────────────────────────┐ │
│  │  Streamlit Dashboard     │   │  Claude API (Anthropic) │ │
│  │  localhost:8501          │   │  レポート生成           │ │
│  └──────────────────────────┘   └────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                     │ Gmail SMTP
                     ▼
              週次レポートメール配信
```

### 起動シーケンス（PC起動時）
```
PC起動
  → Docker Desktop 自動起動
    → n8n コンテナ自動起動（restart: unless-stopped）
  → start_api_server.bat（Windowsスタートアップ登録）
    → api_server.py 常時起動（ポート8765）
```

---

## 3. インフラ・環境構成

### 動作環境
| 項目 | 内容 |
|------|------|
| OS | Windows 11 Home |
| Python | 3.11以上 |
| Docker | Docker Desktop for Windows |
| n8n | v2.11.4（Dockerコンテナ） |
| DB | Supabase（クラウド、PostgreSQL） |

### 主要ライブラリ（requirements.txt）
```
anthropic>=0.85.0      # Claude API（レポート生成）
supabase>=2.4.0        # Supabaseクライアント
python-dotenv>=1.0.0   # 環境変数管理
pandas>=2.0.0          # データ処理
openpyxl>=3.1.0        # Excel生成
requests>=2.31.0       # HTTP通信（JPXデータ取得）
numpy>=1.26.0          # Zスコア・統計計算
reportlab>=4.0.0       # PDF生成
streamlit>=1.30.0      # ダッシュボード
plotly>=5.0.0          # インタラクティブグラフ
```

### 環境変数（config/.env）
```
SUPABASE_URL=https://xxxxxxxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...（service_roleキー）
ANTHROPIC_API_KEY=sk-ant-api03-...
```

---

## 4. データベース設計（Supabase）

Supabaseの無料プラン上にPostgreSQLとして構築。RLSは無効化し、service_roleキーで全操作を行う。

### テーブル一覧

#### weekly_spot（現物週次データ）
```sql
CREATE TABLE weekly_spot (
    id            BIGSERIAL PRIMARY KEY,
    week_date     DATE NOT NULL,           -- 集計週末日（金曜日）
    investor_type TEXT NOT NULL,           -- 投資家区分（下記参照）
    buy_amount    NUMERIC(15,2),           -- 買い越し額（億円）
    sell_amount   NUMERIC(15,2),           -- 売り越し額（億円）
    net_amount    NUMERIC(15,2),           -- NET（億円）買いプラス
    market        TEXT DEFAULT 'prime',    -- prime / standard
    source_url    TEXT,                    -- ソースCSVパス
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (week_date, investor_type, market)
);
```

#### weekly_futures（先物週次データ）
```sql
CREATE TABLE weekly_futures (
    id             BIGSERIAL PRIMARY KEY,
    week_date      DATE NOT NULL,
    investor_type  TEXT NOT NULL,
    futures_type   TEXT NOT NULL,          -- nikkei225_large / topix_large
    long_lots      NUMERIC(12,0),          -- 買い建て枚数
    short_lots     NUMERIC(12,0),          -- 売り建て枚数
    net_lots       NUMERIC(12,0),          -- 差引き枚数（買い越し=正）
    index_close    NUMERIC(10,2),          -- 終値（先物換算用）
    net_amount_oku NUMERIC(15,2),          -- 億円換算
    source_url     TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (week_date, investor_type, futures_type)
);
```

#### weekly_combined（現物+先物合算）
```sql
CREATE TABLE weekly_combined (
    id              BIGSERIAL PRIMARY KEY,
    week_date       DATE NOT NULL,
    investor_type   TEXT NOT NULL,
    spot_net        NUMERIC(15,2),         -- 現物NET（億円）
    futures_net_oku NUMERIC(15,2),         -- 先物NET（億円換算）
    combined_net    NUMERIC(15,2),         -- 合算NET（億円）
    is_twin_engine  BOOLEAN DEFAULT FALSE, -- 現物・先物ともに買い越し
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (week_date, investor_type)
);
```

#### weekly_stats（Zスコア・統計キャッシュ）
```sql
CREATE TABLE weekly_stats (
    id            BIGSERIAL PRIMARY KEY,
    week_date     DATE NOT NULL,
    investor_type TEXT NOT NULL,
    data_type     TEXT NOT NULL,           -- spot / futures / combined
    net_amount    NUMERIC(15,2),
    zscore_26w    NUMERIC(6,3),            -- 26週基準Zスコア
    zscore_52w    NUMERIC(6,3),            -- 52週基準Zスコア
    ma4w          NUMERIC(15,2),           -- 4週移動平均
    wow_change    NUMERIC(15,2),           -- 前週比
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (week_date, investor_type, data_type)
);
```

> **注意:** weekly_statsのZスコアはバックフィル時に誤りがあり信頼できない。ダッシュボードでは weekly_spot/futures から毎回 rolling 計算する。

#### monthly_summary（月次集計）
```sql
CREATE TABLE monthly_summary (
    id              BIGSERIAL PRIMARY KEY,
    year_month      TEXT NOT NULL,         -- 'YYYY-MM' 形式
    investor_type   TEXT NOT NULL,
    spot_net_sum    NUMERIC(15,2),         -- 月間現物NET合計
    futures_net_sum NUMERIC(15,2),         -- 月間先物NET合計
    combined_net    NUMERIC(15,2),         -- 月間合算NET
    week_count      INTEGER,               -- 集計週数
    calculated_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (year_month, investor_type)
);
```

#### reports（レポート管理）
```sql
CREATE TABLE reports (
    id          BIGSERIAL PRIMARY KEY,
    week_date   DATE NOT NULL,
    report_type TEXT NOT NULL,             -- weekly / monthly
    format      TEXT NOT NULL,             -- markdown / excel / pdf
    file_name   TEXT,
    gdrive_url  TEXT,
    content_md  TEXT,                      -- Markdownテキスト全文
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (week_date, report_type, format)
);
```

#### fetch_logs（実行ログ）
```sql
CREATE TABLE fetch_logs (
    id            BIGSERIAL PRIMARY KEY,
    run_at        TIMESTAMPTZ DEFAULT NOW(),
    week_date     DATE,
    status        TEXT,                    -- success / error / partial
    spot_rows     INTEGER DEFAULT 0,
    futures_rows  INTEGER DEFAULT 0,
    error_message TEXT,
    duration_sec  NUMERIC(8,2)
);
```

### 投資家区分コード（investor_type）
| コード | 名称 | 備考 |
|--------|------|------|
| foreign | 海外投資家（外国人） | JPXコード: 60 |
| trust_bank | 信託銀行 | JPXコード: 23（GPIF等） |
| inv_trust | 投資信託 | 現物のみ（先物非対応） |
| individual | 個人投資家 | JPXコード: 30 |
| corporate | 事業法人 | JPXコード: 32 |
| dealer | 自己（証券会社） | JPXコード: 10 |

### Supabase接続の注意事項
- RLS（Row Level Security）は全テーブルで無効化
- `anon`キーではなく`service_role`キーを使用
- 1000行制限: `supabase-py`の`.execute()`は最大1000行。ダッシュボードでは`.range(offset, offset+999)`のページネーションループで対応済み

---

## 5. Pythonバックエンド設計

### ファイル構成
```
C:\CarSol\jpx-analysis\
├── main.py                      メインエントリーポイント
├── api_server.py                n8n連携HTTPサーバー（ポート8765）
├── start_api_server.bat         Windowsスタートアップ登録済み
├── requirements.txt
├── config/
│   └── .env                     環境変数（Git管理外）
├── db/
│   ├── supabase_client.py       Supabase CRUD操作集約
│   └── schema.sql               テーブル定義SQL
├── scripts/
│   ├── fetch_jpx.py             JPXサイトからCSV/XLSを取得
│   ├── parse_spot_xls.py        現物XLSパーサー（行インデックスベース）
│   ├── parse_futures_csv.py     先物CSVパーサー v1.1（列インデックスベース）
│   ├── analyze_jpx.py           合算計算・Zスコア・月次集計
│   ├── build_excel.py           Excelレポート生成（matplotlib画像埋め込み）
│   ├── extract_report_summary.py レポートサマリー抽出（n8n→Gmail用）
│   └── backfill_jpx.py          過去データバックフィル
├── agents/
│   └── report_agent.py          Claude APIでAIレポート生成
├── skills/jpx-investor-data/references/
│   ├── jpx_micro_flows.md       投資家行動原理・CVD解釈知識
│   ├── options_gex_master.md    GEX環境判定・オプション知識
│   ├── global_macro_dynamics.md マクロ文脈・季節性アノマリー
│   └── quant_tech_psychology.md Zスコア解釈・統計的分析知識
├── outputs/
│   ├── reports/                 生成Markdownレポート
│   └── excel/                   生成Excelファイル
└── logs/                        実行ログ
```

### 週次処理フロー（main.py: run_weekly）

```
① データ取得（fetch_jpx.py）
   └─ 自動モード: JPXサイトからXLS/CSVをダウンロード
   └─ 手動モード: ローカルファイルを指定して解析

② Supabaseに保存（supabase_client.py）
   └─ weekly_spot にupsert（on_conflict: week_date, investor_type, market）
   └─ weekly_futures にupsert（on_conflict: week_date, investor_type, futures_type）

③ 合算計算（analyze_jpx.py: build_combined）
   └─ 現物NET + 先物NET（億円換算）= combined_net
   └─ is_twin_engine: 現物・先物ともにNET > 0 かつ投資信託除外
   └─ weekly_combined にupsert

④ Zスコア・統計計算（analyze_jpx.py: build_stats）
   └─ 26週・52週 rolling mean/std でZスコア算出
   └─ 4週MA・前週比計算
   └─ weekly_stats にupsert

⑤ 分析コンテキスト構築（analyze_jpx.py: build_analysis_context）
   └─ 全投資家の最新週・過去比較データを dict に集約

⑥ AIレポート生成（report_agent.py）
   └─ Claude Sonnet 4.6 に系統プロンプト+データ送信
   └─ 7セクション構成のMarkdownレポートを生成

⑦ ファイル保存
   └─ outputs/reports/ にMarkdown保存
   └─ outputs/excel/ にExcel保存
   └─ reportsテーブルにメタデータ保存

⑧ ログ記録（fetch_logs）
```

### CSVパーサーの注意点
現物と先物でフォーマットが異なる:
- **現物**: XLS形式（Excel）。行インデックスベースで投資家区分を特定
- **先物**: CSV形式（ヘッダーなし）。列インデックスベースで数値取得

先物のJPX投資家コード（修正済み v1.1）:
| 区分 | 旧コード（誤） | 正コード |
|------|------------|----------|
| 海外投資家 | 50 | **60** |
| 信託銀行 | 21 | **23** |
| 事業法人 | 22 | **32** |
| 個人 | 30 | 30（変更なし） |
| 自己 | 10 | 10（変更なし） |

---

## 6. n8n自動化設計

### n8n環境
- **バージョン**: 2.11.4
- **起動**: Docker Compose（`config/docker-compose.yml`）
- **ポート**: 5678（管理UI）
- **データ永続化**: `n8n_data` Docker volume

### docker-compose.yml
```yaml
version: "3.8"
services:
  n8n:
    image: docker.n8n.io/n8nio/n8n
    container_name: n8n
    restart: unless-stopped
    ports:
      - "5678:5678"
    volumes:
      - n8n_data:/home/node/.n8n
      - C:\CarSol\jpx-analysis:/CarSol/jpx-analysis  # ホストマウント
    environment:
      - GENERIC_TIMEZONE=Asia/Tokyo
      - TZ=Asia/Tokyo
      - N8N_BLOCK_ENV_ACCESS_IN_NODE=false  # 環境変数アクセス許可
volumes:
  n8n_data:
    external: true
```

### ワークフロー構成

#### メインワークフロー（毎週木曜20時自動実行）

```
[Cron Trigger]          毎週木曜 20:00 JST
       ↓
[HTTP Request]          POST http://host.docker.internal:8765/run
                        → api_server.py に実行を委譲
       ↓
[IF: success判定]       レスポンスの success フィールドを確認
       ↓                        ↓
[HTTP Request]          [エラー通知メール]
GET :8765/summary       失敗時: 管理者にエラー内容送信
       ↓
[Gmail SMTP]            週次レポートサマリーをメール送信
                        宛先: y.ioku1973@gmail.com
```

#### n8n → Windows Python の橋渡し設計

n8nはDockerコンテナ内で動作するため、ホストのPythonを直接実行できない。`host.docker.internal` 経由でホストのHTTPサーバーを呼び出す方式を採用:

```
n8n (Docker)  ──HTTP POST :8765──►  api_server.py (Windows Python)
                                          │
                                    subprocess.run(main.py)
                                          │
                                    ① JPXデータ取得
                                    ② Supabase保存
                                    ③ AIレポート生成
                                    ④ Excel生成
```

### api_server.py エンドポイント
| メソッド | パス | 処理 |
|--------|------|------|
| GET | /health | 死活確認 |
| GET | /summary | レポートサマリー取得（n8n→Gmail用） |
| POST | /run | main.py 実行（週次フル処理） |

### Windowsスタートアップ登録
`start_api_server.bat` をWindowsのスタートアップフォルダに配置。PC起動時に自動でapi_server.pyが起動する。

---

## 7. AIレポート生成設計

### 使用モデル
- **モデル**: claude-sonnet-4-6
- **max_tokens**: 8192
- **方式**: 単一リクエスト（systemプロンプト + userプロンプト）

### 知識ファイル（システムプロンプトに注入）
| ファイル | 内容 |
|---------|------|
| jpx_micro_flows.md | 投資家行動原理・CVD解釈・両輪買いシグナル |
| options_gex_master.md | GEX環境判定・オプション需給・ガンマ影響 |
| global_macro_dynamics.md | マクロ文脈・日銀/FRB・季節性アノマリー |
| quant_tech_psychology.md | Zスコア解釈・統計的分析・アルゴ行動原理 |

### レポート構成（7セクション）
1. エグゼクティブサマリー（3〜5行）
2. マクロ・市場環境（GEX環境・季節性・注目マクロ）
3. 現物（東証プライム）投資家別売買
4. 先物（日経225・TOPIX）投資家別動向
5. 合算（現物+先物換算）
6. 注目セグメント動向（外国人必須・個人・信託銀行）
7. 戦略示唆（GEX対応アプローチ・来週の注目点）

---

## 8. Streamlitダッシュボード

### 起動方法
```powershell
cd C:\CarSol\jpx-analysis
streamlit run dashboard/app.py
# → http://localhost:8501
```

### ページ構成
| ページ | 内容 |
|--------|------|
| app.py（ホーム） | 最新週KPIカード・ツインエンジン判定・4週トレンド |
| 1_現物フロー.py | 投資家別NET推移（折れ線+棒）・市場フィルター |
| 2_先物フロー.py | 日経225/TOPIX先物NET（枚数・億円）・投資家フィルター |
| 3_合算分析.py | 現物vs先物乖離・ツインエンジン発動履歴・累積フロー |
| 4_Zスコア.py | Zスコアヒートマップ・26w vs 52w比較・4週MA（現物のみ） |
| 5_月次集計.py | 月次フロー・ヒートマップ・推移テーブル |

### テーマ設計
- `config.toml`: `base = "light"`（Streamlitネイティブlightテーマを基盤）
- ダークモード: CSS injection で完全上書き（`components/theme.py`）
- KPIカード色: `.kpi-pos`（緑）/`.kpi-neg`（赤）クラスで管理

### CSS設計の重要ルール
- `[stMarkdownContainer] *` ワイルドカード+`!important` **禁止**（KPIカードのinline styleを上書きする）
- ポップオーバーは `body [data-baseweb="..."]` で対応（portal描画のため）
- Plotlyのハードコード色は `get_theme()` で動的切り替え

---

## 9. 運用手順

### 通常運用（全自動）
毎週木曜20時にn8nが自動実行。手動操作は不要。

### 手動実行コマンド
```powershell
cd C:\CarSol\jpx-analysis

# 週次フル処理（今週分）
python main.py

# 特定日付で再実行
python main.py --date 2026-04-03

# レポートのみ再生成（データ取得・DB保存はスキップ）
python main.py --report-only --date 2026-04-03

# 月次サマリー集計
python main.py --monthly 2026-03

# 過去データバックフィル
python scripts/backfill_jpx.py --from 2025-04-04

# Excel全年再生成
python scripts/build_excel.py

# ダッシュボード起動
streamlit run dashboard/app.py
```

### データ確認
- **Supabase管理画面**: https://supabase.com（テーブルエディタで直接確認可）
- **ダッシュボード**: http://localhost:8501（Streamlit起動後）
- **ログ**: `logs/jpx_YYYYMMDD.log`・Supabaseの`fetch_logs`テーブル

---

## 10. エラー対処

| エラー | 原因 | 対処 |
|--------|------|------|
| `SUPABASE_KEY が設定されていない` | .envのキー名誤り | `SUPABASE_SERVICE_KEY` を確認 |
| `weekly_futures テーブルが存在しない` | スキーマ未適用 | Supabase SQL Editorで schema.sql を実行 |
| ダッシュボードのデータが古い | キャッシュ | サイドバーの「キャッシュ更新」ボタン |
| 1000行しか取得されない | Supabase制限 | data_loader.pyのページネーションループで対応済み |
| n8nからapi_serverに繋がらない | api_server未起動 | `python api_server.py` を手動起動 |
| CP932エンコードエラー | Windows絵文字print | extract_report_summary.pyは修正済み |

---

## 11. 今後の拡張計画

| 優先度 | タスク | 概要 |
|--------|--------|------|
| 1 | 先物Zスコア追加 | dashboard/4_Zスコア.py・Excel・週次レポートに先物rolling計算を追加 |
| 2 | 月次レポート自動化 | 月末n8nトリガー・月次AI分析・Gmail配信 |
| 3 | Advisor Tool統合 | Sonnet（実行）+ Opus（解釈助言）の2層構造でレポート品質向上 |

---

## 12. セキュリティ注意事項

- `config/.env` はGit管理外（.gitignore登録推奨）
- Supabaseは `service_role` キーを使用（RLS無効のため外部公開厳禁）
- n8nのGmail認証情報はDocker volume内に保存
- `docker-compose.yml` に環境変数を直書きしているため、ファイルの外部共有不可
