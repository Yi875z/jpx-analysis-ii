-- ============================================================
-- JPX投資主体別売買動向 自動分析システム
-- Supabase スキーマ定義 v1.0
-- Supabase SQL Editor に貼り付けて実行する
-- ============================================================

-- ① 現物週次データ
CREATE TABLE IF NOT EXISTS weekly_spot (
    id              BIGSERIAL PRIMARY KEY,
    week_date       DATE NOT NULL,
    investor_type   TEXT NOT NULL,
    buy_amount      NUMERIC(15,2),
    sell_amount     NUMERIC(15,2),
    net_amount      NUMERIC(15,2),
    market          TEXT DEFAULT 'prime',
    source_url      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (week_date, investor_type, market)
);

-- ② 先物週次データ
CREATE TABLE IF NOT EXISTS weekly_futures (
    id              BIGSERIAL PRIMARY KEY,
    week_date       DATE NOT NULL,
    investor_type   TEXT NOT NULL,
    futures_type    TEXT NOT NULL,
    long_lots       NUMERIC(12,0),
    short_lots      NUMERIC(12,0),
    net_lots        NUMERIC(12,0),
    index_close     NUMERIC(10,2),
    net_amount_oku  NUMERIC(15,2),
    source_url      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (week_date, investor_type, futures_type)
);

-- ③ 合算集計（現物＋先物換算）
CREATE TABLE IF NOT EXISTS weekly_combined (
    id              BIGSERIAL PRIMARY KEY,
    week_date       DATE NOT NULL,
    investor_type   TEXT NOT NULL,
    spot_net        NUMERIC(15,2),
    futures_net_oku NUMERIC(15,2),
    combined_net    NUMERIC(15,2),
    is_twin_engine  BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (week_date, investor_type)
);

-- ④ Zスコア・統計キャッシュ
CREATE TABLE IF NOT EXISTS weekly_stats (
    id              BIGSERIAL PRIMARY KEY,
    week_date       DATE NOT NULL,
    investor_type   TEXT NOT NULL,
    data_type       TEXT NOT NULL,  -- spot / futures / combined
    net_amount      NUMERIC(15,2),
    zscore_26w      NUMERIC(6,3),
    zscore_52w      NUMERIC(6,3),
    ma4w            NUMERIC(15,2),
    wow_change      NUMERIC(15,2),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (week_date, investor_type, data_type)
);

-- ⑤ 月次サマリー
CREATE TABLE IF NOT EXISTS monthly_summary (
    id              BIGSERIAL PRIMARY KEY,
    year_month      TEXT NOT NULL,
    investor_type   TEXT NOT NULL,
    spot_net_sum    NUMERIC(15,2),
    futures_net_sum NUMERIC(15,2),
    combined_net    NUMERIC(15,2),
    week_count      INTEGER,
    calculated_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (year_month, investor_type)
);

-- ⑥ 生成レポート管理
CREATE TABLE IF NOT EXISTS reports (
    id              BIGSERIAL PRIMARY KEY,
    week_date       DATE NOT NULL,
    report_type     TEXT NOT NULL,  -- weekly / monthly
    format          TEXT NOT NULL,  -- markdown / excel / pdf
    file_name       TEXT,
    gdrive_url      TEXT,
    content_md      TEXT,
    generated_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (week_date, report_type, format)
);

-- ⑦ 実行ログ
CREATE TABLE IF NOT EXISTS fetch_logs (
    id              BIGSERIAL PRIMARY KEY,
    run_at          TIMESTAMPTZ DEFAULT NOW(),
    week_date       DATE,
    status          TEXT,  -- success / error / partial
    spot_rows       INTEGER DEFAULT 0,
    futures_rows    INTEGER DEFAULT 0,
    error_message   TEXT,
    duration_sec    NUMERIC(8,2)
);

-- ============================================================
-- インデックス（パフォーマンス）
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_weekly_spot_date     ON weekly_spot(week_date DESC);
CREATE INDEX IF NOT EXISTS idx_weekly_futures_date  ON weekly_futures(week_date DESC);
CREATE INDEX IF NOT EXISTS idx_weekly_combined_date ON weekly_combined(week_date DESC);
CREATE INDEX IF NOT EXISTS idx_monthly_ym           ON monthly_summary(year_month DESC);
CREATE INDEX IF NOT EXISTS idx_reports_date         ON reports(week_date DESC);

-- ============================================================
-- RLS（Row Level Security）は無効化 - サービスキーで全操作
-- ============================================================
ALTER TABLE weekly_spot      DISABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_futures   DISABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_combined  DISABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_stats     DISABLE ROW LEVEL SECURITY;
ALTER TABLE monthly_summary  DISABLE ROW LEVEL SECURITY;
ALTER TABLE reports          DISABLE ROW LEVEL SECURITY;
ALTER TABLE fetch_logs       DISABLE ROW LEVEL SECURITY;
