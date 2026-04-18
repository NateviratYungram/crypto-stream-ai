"""
CryptoStream AI — yfinance Ingestion Service
=============================================
Polls Yahoo Finance and persists OHLCV candles into the market_ohlcv table.

Priority groups:
  A — MACRO (11 symbols):    every 15 min  | timeframes: 15m, 1h, 1d
  B — NASDAQ 100 (100 syms): every 24 h    | timeframe:  1d only
  C — S&P 500 (~500 syms):   every 24 h    | timeframe:  1d only (batched)

On first start the service backfills:
  - MACRO   → 60 days of 15m + 1 year of 1d
  - Stocks  → 1 year of 1d

Run standalone:
    python -m services.yfinance_ingestion_service

Inside Docker (added to docker-compose.yml as 'yfinance-ingester').
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

import pandas as pd
import psycopg2
import psycopg2.extras
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("yfinance_ingester")

# ---------------------------------------------------------------------------
# DB Config
# ---------------------------------------------------------------------------
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "dbname":   os.getenv("DB_NAME", "crypto_stream_db"),
    "user":     os.getenv("DB_USER", "user"),
    "password": os.getenv("DB_PASS", "password"),
}

# ---------------------------------------------------------------------------
# Symbol groups
# ---------------------------------------------------------------------------
# Import inline to avoid circular deps when run as __main__
def _load_symbols():
    from intelligence.constants import MACRO_MAPPING, NASDAQ_100_TICKERS, SP500_TICKERS
    return MACRO_MAPPING, NASDAQ_100_TICKERS, SP500_TICKERS

# Poll intervals (seconds)
MACRO_POLL_INTERVAL  = int(os.getenv("YF_MACRO_POLL_INTERVAL",  str(15 * 60)))   # 15 min
STOCKS_POLL_INTERVAL = int(os.getenv("YF_STOCKS_POLL_INTERVAL", str(24 * 3600))) # 24 h

# yfinance batch size (avoid rate limiting)
YF_BATCH_SIZE = int(os.getenv("YF_BATCH_SIZE", "20"))
YF_BATCH_SLEEP = float(os.getenv("YF_BATCH_SLEEP", "2.0"))  # seconds between batches

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def upsert_ohlcv(conn, rows: List[dict]) -> int:
    """
    Bulk upsert OHLCV rows into market_ohlcv.
    Uses ON CONFLICT DO UPDATE to keep the latest fetched_at and close price.
    Returns number of rows inserted/updated.
    """
    if not rows:
        return 0

    insert_sql = """
        INSERT INTO market_ohlcv (symbol, timeframe, ts, open, high, low, close, volume, source)
        VALUES %s
        ON CONFLICT (symbol, timeframe, ts) DO UPDATE
            SET open       = EXCLUDED.open,
                high       = EXCLUDED.high,
                low        = EXCLUDED.low,
                close      = EXCLUDED.close,
                volume     = EXCLUDED.volume,
                fetched_at = NOW()
    """
    tuples = [
        (r["symbol"], r["timeframe"], r["ts"],
         r["open"], r["high"], r["low"], r["close"],
         r.get("volume", 0.0), "yfinance")
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, insert_sql, tuples, page_size=500)
    conn.commit()
    return len(tuples)


# ---------------------------------------------------------------------------
# Exponential backoff helper
# ---------------------------------------------------------------------------
def _with_backoff(fn, max_retries: int = 4, base_delay: float = 5.0):
    """
    Call fn() with exponential backoff on failure.
    Delays: 5s, 10s, 20s, 40s  (doubles each attempt, caps at 60s).
    Returns fn() result, or raises the last exception after max_retries.
    """
    delay = base_delay
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt == max_retries:
                raise
            wait = min(delay * (2 ** (attempt - 1)), 60.0)
            logger.warning(
                f"Attempt {attempt}/{max_retries} failed: {e} — retrying in {wait:.0f}s"
            )
            time.sleep(wait)


# ---------------------------------------------------------------------------
# yfinance fetch + normalise
# ---------------------------------------------------------------------------
def fetch_ohlcv(tickers: List[str], period: str, interval: str) -> List[dict]:
    """
    Download OHLCV from yfinance for a list of tickers.
    Retries with exponential backoff on network/rate-limit errors.
    Returns a flat list of row dicts ready for upsert_ohlcv().
    """
    if not tickers:
        return []

    def _download():
        return yf.download(
            tickers,
            period=period,
            interval=interval,
            progress=False,
            group_by="ticker",
            auto_adjust=True,
            threads=True,
        )

    try:
        raw = _with_backoff(_download)
    except Exception as e:
        logger.error(f"yfinance download failed after retries ({tickers[:3]}…): {e}")
        return []

    if raw is None or raw.empty:
        return []

    rows = []

    # Single ticker: columns are just Open/High/Low/Close/Volume
    if len(tickers) == 1:
        ticker = tickers[0]
        df = raw.copy()
        rows.extend(_df_to_rows(df, ticker, interval))
    else:
        # Multi ticker: MultiIndex (Price, Ticker) columns
        for ticker in tickers:
            try:
                if ticker in raw.columns.get_level_values(1):
                    df = raw.xs(ticker, axis=1, level=1).dropna(how="all")
                elif ticker in raw.columns.get_level_values(0):
                    df = raw[ticker].dropna(how="all")
                else:
                    continue
                rows.extend(_df_to_rows(df, ticker, interval))
            except Exception as e:
                logger.warning(f"Failed to extract data for {ticker}: {e}")

    return rows


def _df_to_rows(df: pd.DataFrame, ticker: str, interval: str) -> List[dict]:
    """Convert a single-ticker OHLCV DataFrame to row dicts."""
    rows = []
    # Normalise column names (handle both 'Adj Close' and 'Close')
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    if "Adj Close" in df.columns:
        df["Close"] = df["Adj Close"]

    # Ensure index is datetime
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.dropna(subset=["Close"])

    for ts, row in df.iterrows():
        try:
            rows.append({
                "symbol":    ticker,
                "timeframe": interval,
                "ts":        ts.to_pydatetime(),
                "open":      float(row.get("Open",   row["Close"])),
                "high":      float(row.get("High",   row["Close"])),
                "low":       float(row.get("Low",    row["Close"])),
                "close":     float(row["Close"]),
                "volume":    float(row.get("Volume", 0.0) or 0.0),
            })
        except Exception:
            continue
    return rows


# ---------------------------------------------------------------------------
# Backfill on startup
# ---------------------------------------------------------------------------
def backfill(conn, macro_mapping: dict, nasdaq: List[str], sp500: List[str]):
    """
    Download historical data on first start.
    - MACRO: 60d of 15m + 1y of 1d
    - Stocks (NASDAQ100 + SP500): 1y of 1d
    """
    logger.info("=== Starting historical backfill ===")

    macro_tickers = list(macro_mapping.values())

    # 1. Macro 15m (60 days)
    logger.info(f"Backfilling {len(macro_tickers)} macro tickers @ 15m / 60d...")
    rows = fetch_ohlcv(macro_tickers, period="60d", interval="15m")
    if rows:
        n = upsert_ohlcv(conn, rows)
        logger.info(f"  → Upserted {n:,} rows (macro 15m)")

    # 2. Macro 1h (180 days)
    rows = fetch_ohlcv(macro_tickers, period="180d", interval="1h")
    if rows:
        n = upsert_ohlcv(conn, rows)
        logger.info(f"  → Upserted {n:,} rows (macro 1h)")

    # 3. Macro 1d (2 years)
    rows = fetch_ohlcv(macro_tickers, period="2y", interval="1d")
    if rows:
        n = upsert_ohlcv(conn, rows)
        logger.info(f"  → Upserted {n:,} rows (macro 1d)")

    # 4. NASDAQ 100 + SP500 daily — batched to avoid rate limits
    all_stocks = list(set(nasdaq + sp500))
    logger.info(f"Backfilling {len(all_stocks)} stock tickers @ 1d / 1y (batched)...")
    total = 0
    for i in range(0, len(all_stocks), YF_BATCH_SIZE):
        batch = all_stocks[i: i + YF_BATCH_SIZE]
        rows = fetch_ohlcv(batch, period="1y", interval="1d")
        if rows:
            total += upsert_ohlcv(conn, rows)
        time.sleep(YF_BATCH_SLEEP)

    logger.info(f"  → Upserted {total:,} rows (stocks 1d)")
    logger.info("=== Backfill complete ===")


# ---------------------------------------------------------------------------
# Incremental refresh
# ---------------------------------------------------------------------------
def refresh_macro(conn, macro_mapping: dict):
    """Fetch the latest 15m / 1h candles for macro symbols."""
    tickers = list(macro_mapping.values())
    logger.info(f"Refreshing {len(tickers)} macro tickers @ 15m + 1h...")

    for interval, period in [("15m", "2d"), ("1h", "7d"), ("1d", "5d")]:
        rows = fetch_ohlcv(tickers, period=period, interval=interval)
        if rows:
            n = upsert_ohlcv(conn, rows)
            logger.info(f"  macro {interval}: upserted {n:,} rows")


def refresh_stocks(conn, nasdaq: List[str], sp500: List[str]):
    """Fetch the latest daily candle for all stocks (batched)."""
    all_stocks = list(set(nasdaq + sp500))
    logger.info(f"Refreshing {len(all_stocks)} stock tickers @ 1d...")
    total = 0
    for i in range(0, len(all_stocks), YF_BATCH_SIZE):
        batch = all_stocks[i: i + YF_BATCH_SIZE]
        rows = fetch_ohlcv(batch, period="5d", interval="1d")
        if rows:
            total += upsert_ohlcv(conn, rows)
        time.sleep(YF_BATCH_SLEEP)
    logger.info(f"  stocks 1d: upserted {total:,} rows")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    logger.info("=" * 60)
    logger.info("CryptoStream AI — yfinance Ingestion Service")
    logger.info(f"DB: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}")
    logger.info(f"Macro poll interval : {MACRO_POLL_INTERVAL // 60} min")
    logger.info(f"Stocks poll interval: {STOCKS_POLL_INTERVAL // 3600} h")
    logger.info("=" * 60)

    MACRO_MAPPING, NASDAQ_100_TICKERS, SP500_TICKERS = _load_symbols()

    # Wait for DB to be ready (Docker startup race)
    for attempt in range(30):
        try:
            conn = get_conn()
            logger.info("Connected to PostgreSQL")
            break
        except Exception as e:
            logger.warning(f"DB not ready (attempt {attempt+1}/30): {e}")
            time.sleep(5)
    else:
        logger.error("Could not connect to PostgreSQL after 30 attempts. Exiting.")
        return

    # One-time backfill on startup
    try:
        backfill(conn, MACRO_MAPPING, NASDAQ_100_TICKERS, SP500_TICKERS)
    except Exception as e:
        logger.error(f"Backfill error: {e}", exc_info=True)

    last_macro_refresh  = 0.0
    last_stocks_refresh = 0.0

    while True:
        now = time.time()
        try:
            if now - last_macro_refresh >= MACRO_POLL_INTERVAL:
                refresh_macro(conn, MACRO_MAPPING)
                last_macro_refresh = now

            if now - last_stocks_refresh >= STOCKS_POLL_INTERVAL:
                refresh_stocks(conn, NASDAQ_100_TICKERS, SP500_TICKERS)
                last_stocks_refresh = now

        except psycopg2.OperationalError:
            logger.warning("DB connection lost — reconnecting...")
            try:
                conn = get_conn()
            except Exception as e:
                logger.error(f"Reconnect failed: {e}")

        except Exception as e:
            logger.error(f"Refresh error: {e}", exc_info=True)

        # Sleep until next macro poll is due
        sleep_for = max(30, MACRO_POLL_INTERVAL - (time.time() - last_macro_refresh))
        logger.debug(f"Sleeping {sleep_for:.0f}s until next macro refresh...")
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
