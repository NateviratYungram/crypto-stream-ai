-- Create table for storing individual enriched trades
CREATE TABLE IF NOT EXISTS enriched_trades (
    trade_id BIGINT PRIMARY KEY,
    symbol VARCHAR(20),
    price DECIMAL(20, 8),
    quantity DECIMAL(20, 8),
    timestamp BIGINT,
    is_buyer_maker BOOLEAN,
    is_whale BOOLEAN,
    ingestion_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create table for 1-minute aggregated market metrics
CREATE TABLE IF NOT EXISTS market_metrics (
    window_start TIMESTAMP,
    window_end TIMESTAMP,
    symbol VARCHAR(20),
    avg_price DECIMAL(20, 8), -- VWAP
    total_volume DECIMAL(20, 8),
    trade_count INT,
    PRIMARY KEY (window_start, symbol)
);

-- Create table for Data Quality audit log (Dead Letter Queue records)
-- Banking Relevance: Acts as an Audit Trail for regulators (ธปท., AMLO)
-- to prove that invalid data was caught, isolated, and not mixed with clean data.
CREATE TABLE IF NOT EXISTS data_quality_log (
    id             BIGSERIAL PRIMARY KEY,
    trade_id       VARCHAR(50),
    raw_payload    JSONB,           -- Full original message for investigation
    error_reason   VARCHAR(255),    -- e.g. 'price_is_zero', 'null_quantity', 'negative_price'
    detected_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast lookup by detection time (for daily DQ reports)
CREATE INDEX IF NOT EXISTS idx_dq_detected_at ON data_quality_log (detected_at);

-- Create table for Daily Aggregation Summary (populated by Airflow DAG)
-- Banking Relevance: Mirrors the EOD (End-of-Day) Daily Summary Report
-- that banks must produce and retain for regulatory review (ธปท., SEC).
CREATE TABLE IF NOT EXISTS daily_summary (
    report_date     DATE         NOT NULL,
    symbol          VARCHAR(20)  NOT NULL,
    open_price      DECIMAL(20, 8),        -- First trade price of the day
    high_price      DECIMAL(20, 8),        -- Highest trade price
    low_price       DECIMAL(20, 8),        -- Lowest trade price
    close_price     DECIMAL(20, 8),        -- Last trade price of the day
    total_volume    DECIMAL(20, 8),        -- Total BTC volume traded
    trade_count     INT,                   -- Number of trades
    whale_count     INT,                   -- Number of whale trades (qty > 0.5)
    whale_volume    DECIMAL(20, 8),        -- Total volume from whale trades
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (report_date, symbol)
);

-- Index for fast date-range queries in BI dashboards
CREATE INDEX IF NOT EXISTS idx_daily_summary_date ON daily_summary (report_date DESC);

-- Create table for MCP Audit Logs (Banking Security Requirement)
-- Logs every AI-generated SQL query to perfectly trace access and modifications
CREATE TABLE IF NOT EXISTS mcp_audit_log (
    id             SERIAL PRIMARY KEY,
    api_key_hash   VARCHAR(64) NOT NULL,
    sql_query      TEXT NOT NULL,
    row_count      INTEGER,
    duration_ms    INTEGER,
    client_ip      VARCHAR(45),
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- Precomputed OHLCV Candlestick Aggregations
-- ==========================================
-- Banking Relevance: Fast path for AI and Dashboards to fetch exact candlestick
-- charts without overloading the Database querying raw trades.

CREATE TABLE IF NOT EXISTS candles_m5 (
    window_start TIMESTAMP,
    window_end TIMESTAMP,
    symbol VARCHAR(20),
    open_price DECIMAL(20, 8),
    high_price DECIMAL(20, 8),
    low_price DECIMAL(20, 8),
    close_price DECIMAL(20, 8),
    total_volume DECIMAL(20, 8),
    trade_count INT,
    PRIMARY KEY (window_start, symbol)
);

CREATE TABLE IF NOT EXISTS candles_m15 (
    window_start TIMESTAMP,
    window_end TIMESTAMP,
    symbol VARCHAR(20),
    open_price DECIMAL(20, 8),
    high_price DECIMAL(20, 8),
    low_price DECIMAL(20, 8),
    close_price DECIMAL(20, 8),
    total_volume DECIMAL(20, 8),
    trade_count INT,
    PRIMARY KEY (window_start, symbol)
);

CREATE TABLE IF NOT EXISTS candles_h1 (
    window_start TIMESTAMP,
    window_end TIMESTAMP,
    symbol VARCHAR(20),
    open_price DECIMAL(20, 8),
    high_price DECIMAL(20, 8),
    low_price DECIMAL(20, 8),
    close_price DECIMAL(20, 8),
    total_volume DECIMAL(20, 8),
    trade_count INT,
    PRIMARY KEY (window_start, symbol)
);

CREATE TABLE IF NOT EXISTS candles_h4 (
    window_start TIMESTAMP,
    window_end TIMESTAMP,
    symbol VARCHAR(20),
    open_price DECIMAL(20, 8),
    high_price DECIMAL(20, 8),
    low_price DECIMAL(20, 8),
    close_price DECIMAL(20, 8),
    total_volume DECIMAL(20, 8),
    trade_count INT,
    PRIMARY KEY (window_start, symbol)
);

-- ==========================================
-- Feature Store: Per-Symbol Daily Features
-- ==========================================
-- Precomputed statistical features for every tracked symbol.
-- Populated nightly by Airflow feature_store_dag (reads from market_ohlcv).
-- Enables AI to answer cross-asset and risk questions instantly from DB
-- instead of recomputing from scratch on every request.
CREATE TABLE IF NOT EXISTS market_features (
    symbol              VARCHAR(30)   NOT NULL,
    date                DATE          NOT NULL,
    -- ── Price returns (decimal fraction, e.g. 0.0325 = +3.25%) ──────────────
    return_1d           DECIMAL(10,6),
    return_7d           DECIMAL(10,6),
    return_30d          DECIMAL(10,6),
    return_90d          DECIMAL(10,6),
    return_365d         DECIMAL(10,6),
    -- ── Realized volatility (annualized, e.g. 0.45 = 45% annual vol) ────────
    volatility_7d       DECIMAL(10,6),
    volatility_30d      DECIMAL(10,6),
    volatility_90d      DECIMAL(10,6),
    -- ── Pearson correlation of daily returns vs benchmarks ───────────────────
    corr_vs_sp500_30d   DECIMAL(8,4),
    corr_vs_sp500_90d   DECIMAL(8,4),
    corr_vs_btc_30d     DECIMAL(8,4),
    corr_vs_btc_90d     DECIMAL(8,4),
    corr_vs_gold_30d    DECIMAL(8,4),
    -- ── Beta vs SP500 (90-day rolling OLS slope) ─────────────────────────────
    beta_vs_sp500       DECIMAL(8,4),
    -- ── Price position within 52-week range (%) ──────────────────────────────
    pct_from_52w_high   DECIMAL(10,4),   -- negative = below 52w high
    pct_from_52w_low    DECIMAL(10,4),   -- positive = above 52w low
    -- ── Relative strength vs SP500 over 30 days (percentage points) ──────────
    rel_strength_30d    DECIMAL(10,4),   -- positive = outperforming SP500
    computed_at         TIMESTAMPTZ   DEFAULT NOW(),
    PRIMARY KEY (symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_market_features_date
    ON market_features (date DESC, symbol);

-- ==========================================
-- Feature Store: Daily Global Market Regime
-- ==========================================
-- One row per day summarising the overall market environment.
-- Lets AI answer regime questions ("risk-on or risk-off?") in < 1ms.
CREATE TABLE IF NOT EXISTS market_regime (
    date                DATE         PRIMARY KEY,
    -- Market stress proxies
    sp500_vol_30d       DECIMAL(10,6),   -- SP500 realized vol (VIX proxy)
    crypto_vol_30d      DECIMAL(10,6),   -- Average BTC+ETH realized vol
    -- Crypto-macro coupling
    btc_sp500_corr_30d  DECIMAL(8,4),    -- rolling 30d BTC/SP500 correlation
    -- Regime classification
    regime              VARCHAR(15)  NOT NULL,  -- 'RISK_ON' | 'RISK_OFF' | 'NEUTRAL'
    regime_confidence   DECIMAL(5,2),           -- 0-100
    regime_drivers      JSONB,                  -- ["high_sp500_vol", "btc_decoupling", ...]
    -- Trend context
    sp500_vs_ma200      DECIMAL(10,4),  -- % SP500 is above/below its 200-day MA
    btc_vs_ma200        DECIMAL(10,4),  -- % BTC is above/below its 200-day MA
    computed_at         TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_regime_date
    ON market_regime (date DESC);

-- ==========================================
-- AI Trade Memory
-- ==========================================
-- Stores every trading decision the AI makes so it can learn from past
-- successes and failures (queried by recall_memories tool).
-- Populated by: intelligence/tools/market_tools.py → remember_trade()
-- embedding: 768-dim vector from Gemini text-embedding-004, enables semantic
-- similarity search ("find trades from conditions similar to NOW")
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS trade_memory (
    id                BIGSERIAL    PRIMARY KEY,
    symbol            VARCHAR(20)  NOT NULL,
    side              VARCHAR(5)   NOT NULL,         -- 'BUY' | 'SELL'
    entry_price       DECIMAL(20, 8) NOT NULL,
    reasoning         TEXT,
    outcome           VARCHAR(10),                  -- 'WIN' | 'LOSS' | NULL (pending)
    pnl_pct           DECIMAL(10, 4),               -- e.g. 3.25 = +3.25%
    market_conditions JSONB,                        -- snapshot of indicators at decision time
    embedding         vector(768),                  -- Gemini text-embedding-004 of reasoning+conditions
    timestamp         TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_memory_symbol
    ON trade_memory (symbol, timestamp DESC);

-- IVFFlat index for fast approximate nearest-neighbour search (cosine distance)
-- Drop and recreate once table has > 1000 rows for best recall
CREATE INDEX IF NOT EXISTS idx_trade_memory_embedding
    ON trade_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ==========================================
-- yfinance Market OHLCV Store
-- ==========================================
-- Persists Stock, Macro, and Index OHLCV data fetched from Yahoo Finance.
-- Enables: faster AI responses (no live API call), longer intraday history
-- (beyond yfinance's 7-day 1m limit), and cross-asset correlation analysis.
--
-- Populated by: services/yfinance_ingestion_service.py (continuous)
--               airflow/dags/yfinance_ingestion_dag.py  (daily batch)
-- Queried by:   intelligence/technical_engine.py         (DB-first lookup)
CREATE TABLE IF NOT EXISTS market_ohlcv (
    id          BIGSERIAL    PRIMARY KEY,
    symbol      VARCHAR(30)  NOT NULL,   -- e.g. 'NVDA', 'GC=F', 'BTC-USD', '^GSPC'
    timeframe   VARCHAR(5)   NOT NULL,   -- '1m', '5m', '15m', '1h', '1d'
    ts          TIMESTAMPTZ  NOT NULL,   -- candle open time (UTC)
    -- DECIMAL(20,8) intentional: financial prices must never use IEEE-754 float
    -- (0.1 + 0.2 ≠ 0.3 in float). Consistent with all other tables in schema.
    open        DECIMAL(20, 8) NOT NULL,
    high        DECIMAL(20, 8) NOT NULL,
    low         DECIMAL(20, 8) NOT NULL,
    close       DECIMAL(20, 8) NOT NULL,
    volume      DECIMAL(20, 8),
    source      VARCHAR(20)  DEFAULT 'yfinance',
    fetched_at  TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (symbol, timeframe, ts)
);

-- Migration guard: if table already exists with DOUBLE PRECISION columns,
-- run this once manually to correct the types:
--   ALTER TABLE market_ohlcv
--     ALTER COLUMN open  TYPE DECIMAL(20,8),
--     ALTER COLUMN high  TYPE DECIMAL(20,8),
--     ALTER COLUMN low   TYPE DECIMAL(20,8),
--     ALTER COLUMN close TYPE DECIMAL(20,8),
--     ALTER COLUMN volume TYPE DECIMAL(20,8);

-- Composite index for the most common query pattern: symbol + timeframe + recent time
CREATE INDEX IF NOT EXISTS idx_market_ohlcv_lookup
    ON market_ohlcv (symbol, timeframe, ts DESC);

-- ==========================================
-- News Sentiment Store
-- ==========================================
-- Persists RSS news headlines + Gemini sentiment scores so the AI agent
-- can query historical sentiment trends instead of re-fetching every request.
--
-- Populated by: intelligence/agents/sentiment_agent.py (on each analysis)
-- Queried by:   AI tool get_sentiment_history(symbol, days)
CREATE TABLE IF NOT EXISTS news_sentiment (
    id              BIGSERIAL    PRIMARY KEY,
    symbol          VARCHAR(20)  NOT NULL,           -- e.g. 'BTC', 'NVDA', 'GOLD'
    asset_type      VARCHAR(10)  NOT NULL,           -- 'CRYPTO' | 'MACRO' | 'STOCK'
    score           SMALLINT     NOT NULL,           -- -100 to +100 (Gemini output)
    label           VARCHAR(10)  NOT NULL,           -- 'BULLISH' | 'BEARISH' | 'NEUTRAL'
    headline_count  SMALLINT,                        -- number of articles analysed
    top_headlines   JSONB,                           -- [{title, source, published}] top 3
    raw_report      TEXT,                            -- full Gemini reasoning text
    analysed_at     TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_sentiment_symbol_ts
    ON news_sentiment (symbol, analysed_at DESC);

CREATE INDEX IF NOT EXISTS idx_news_sentiment_recent
    ON news_sentiment (analysed_at DESC);

-- ==========================================
-- User Accounts (Phase 16 — Auth)
-- ==========================================
-- Stored in SQLite (persistence.db) not PostgreSQL.
-- This DDL is here for documentation only.
-- CREATE TABLE IF NOT EXISTS users (
--     id            TEXT PRIMARY KEY,
--     email         TEXT UNIQUE NOT NULL,
--     username      TEXT UNIQUE NOT NULL,
--     full_name     TEXT NOT NULL,
--     phone         TEXT,
--     country       TEXT,
--     account_type  TEXT NOT NULL DEFAULT 'retail',
--     bio           TEXT,
--     password_hash TEXT NOT NULL,
--     created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
-- );
