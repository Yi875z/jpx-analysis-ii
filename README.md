# JPX投資主体別売買動向 自動分析システム

Supabase × Claude API による毎週木曜日の需給分析自動化

---

## セットアップ手順

### 1. Supabaseのテーブル作成
Supabase > SQL Editor に `db/schema.sql` を貼り付けて実行

### 2. 環境変数の設定
```bash
cp config/.env.example config/.env
# .env を編集して各キーを入力
```

### 3. ライブラリのインストール
```bash
pip install -r requirements.txt
```

### 4. 動作テスト（手動実行）
```bash
# 自動取得モード
python main.py

# CSVを手動で渡すモード
python main.py --spot spot.csv --futures futures.csv --date 2025-01-10

# 月次集計のみ
python main.py --monthly 2025-01

# レポートのみ再生成（DB蓄積済みデータを使用）
python main.py --report-only --date 2025-01-10
```

### 5. n8nへの登録
n8n > Workflows > Import から `config/n8n_workflow.json` をインポート

---

## ディレクトリ構成

```
jpx-system/
├── main.py                    # エントリーポイント
├── requirements.txt
├── config/
│   ├── .env.example           # 環境変数テンプレート
│   └── n8n_workflow.json      # n8nワークフロー定義
├── db/
│   ├── schema.sql             # Supabaseテーブル定義
│   └── supabase_client.py     # DB操作モジュール
├── scripts/
│   ├── fetch_jpx.py           # JPXデータ取得・パース
│   ├── analyze_jpx.py         # 集計・Zスコア計算
│   └── build_excel.py         # Excel累積ファイル生成
├── agents/
│   └── report_agent.py        # Claude APIレポート生成
├── skills/
│   └── jpx-investor-data/     # 知識ファイル（参照用）
│       └── references/
├── outputs/
│   ├── reports/               # 生成Markdownレポート
│   └── excel/                 # 生成Excelファイル
└── logs/                      # 実行ログ
```

---

## 実行タイムライン（毎週木曜日）

| 時刻 | 処理 |
|------|------|
| 20:00 | n8n Cron起動 |
| 20:01 | JPXサイトからCSV自動DL |
| 20:05 | Supabaseにupsert（蓄積） |
| 20:10 | Zスコア・統計計算 |
| 20:15 | Claude APIでレポート生成 |
| 20:25 | Markdownレポート・Excel保存 |
| 20:30 | Gmail完了通知 |

---

## Supabaseテーブル構成

| テーブル | 用途 |
|---------|------|
| `weekly_spot` | 現物週次（投資家別） |
| `weekly_futures` | 先物週次（投資家別） |
| `weekly_combined` | 現物＋先物合算 |
| `weekly_stats` | Zスコア・統計キャッシュ |
| `monthly_summary` | 月次集計 |
| `reports` | 生成レポートメタ管理 |
| `fetch_logs` | 実行ログ |
