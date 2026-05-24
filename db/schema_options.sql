-- ============================================================
-- weekly_options テーブル
-- 投資部門別 オプション売買状況（週次）
-- 対象: 日経225オプション / 日経225ミニオプション の コール・プット
-- ============================================================

CREATE TABLE IF NOT EXISTS weekly_options (
    id              BIGSERIAL PRIMARY KEY,
    week_date       DATE NOT NULL,
    investor_type   TEXT NOT NULL,            -- foreign / individual / trust_bank / inv_trust / corporate / dealer など
    option_type     TEXT NOT NULL,            -- nikkei225_call / nikkei225_put / nikkei225_mini_call / nikkei225_mini_put
    long_lots       BIGINT,                   -- 買 (gross 枚数)
    short_lots      BIGINT,                   -- 売 (gross 枚数)
    net_lots        BIGINT,                   -- 差引 (買い越し=正)
    long_amount     BIGINT,                   -- 買 金額（円・プレミアム合計）
    short_amount    BIGINT,                   -- 売 金額
    net_amount_oku  NUMERIC,                  -- 差引 金額 億円
    source_url      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT weekly_options_unique
        UNIQUE (week_date, investor_type, option_type)
);

CREATE INDEX IF NOT EXISTS weekly_options_week_idx
    ON weekly_options (week_date DESC);
CREATE INDEX IF NOT EXISTS weekly_options_inv_opt_idx
    ON weekly_options (investor_type, option_type, week_date DESC);

-- 既存の reports テーブル(format='markdown'のメタ)は流用する。
-- weekly_combined / weekly_stats は今回未拡張（後続Phaseで判断）。
