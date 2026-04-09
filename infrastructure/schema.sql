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
