"""
CryptoStream AI — yfinance Ingestion Service
=============================================
Polls Yahoo Finance and persists OHLCV candles into the market_ohlcv table.

Priority groups:
  A — MT5 Assets (Tradeable): every 15 min  | timeframes: 15m, 1h, 4h, 1d
  B — Removed (On-demand only)
  C — Removed (On-demand only)

On first start the service backfills maximum available depth:
  - 15m → 60 days (Yahoo Limit)
  - 1h  → 730 days / 2 years (Yahoo Limit)
  - 4h  → 2 years
  - 1d  → 10 years+ (Historical Depth)

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
# Import inline to avoid circular deps
def _load_symbols():
    from intelligence.ml.signal_model import TRADE_TRAIN_SYMBOLS
    # Extract unique tickers from the (symbol, class, tf) tuples
    tickers = list(set([s[0] for s in TRADE_TRAIN_SYMBOLS]))
    return tickers

# Poll interval (seconds)
MT5_POLL_INTERVAL = int(os.getenv("MT5_POLL_INTERVAL", str(15 * 60)))  # 15 min

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
def fetch_ohlcv(symbols: List[str], period: str, interval: str) -> List[dict]:
    """
    Download OHLCV from yfinance.
    - symbols: MT5 style names (e.g. BTCUSD, GOLD)
    Maps them to yf tickers (e.g. BTC-USD, GC=F) for download.
    Returns rows with MT5 style names for database.
    """
    if not symbols:
        return []

    from intelligence.constants import MACRO_MAPPING
    # Map symbols to tickers
    ticker_to_symbol = {MACRO_MAPPING.get(s, s): s for s in symbols}
    tickers = list(ticker_to_symbol.keys())

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
        logger.error(f"yfinance download failed ({tickers[:3]}…): {e}")
        return []

    if raw is None or raw.empty:
        return []

    rows = []
    if len(tickers) == 1:
        ticker = tickers[0]
        symbol = ticker_to_symbol[ticker]
        rows.extend(_df_to_rows(raw, symbol, interval))
    else:
        for ticker, symbol in ticker_to_symbol.items():
            try:
                if ticker in raw.columns.get_level_values(0):
                    df = raw[ticker].dropna(how="all")
                    rows.extend(_df_to_rows(df, symbol, interval))
            except Exception as e:
                logger.warning(f"Failed to extract {ticker}/{symbol}: {e}")

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
def backfill(conn, symbols: List[str]):
    """
    Download maximum historical data for tradeable assets on startup.
    Yahoo Finance Limits:
    - 15m: max 60d
    - 1h:  max 730d (2 years)
    - 1d:  max (we take 10y)
    """
    logger.info("=== Starting Deep Historical Backfill (MT5 Assets) ===")

    # 1. 15m (60 days - Yahoo Limit)
    logger.info(f"Backfilling {len(symbols)} assets @ 15m / 60d (MAX)...")
    rows = fetch_ohlcv(symbols, period="60d", interval="15m")
    if rows:
        n = upsert_ohlcv(conn, rows)
        logger.info(f"  → Upserted {n:,} rows (15m)")

    # 2. 1h (2 years - Yahoo Limit)
    logger.info(f"Backfilling {len(symbols)} assets @ 1h / 730d (MAX)...")
    rows = fetch_ohlcv(symbols, period="730d", interval="1h")
    if rows:
        n = upsert_ohlcv(conn, rows)
        logger.info(f"  → Upserted {n:,} rows (1h)")

    # 3. 4h (2 years)
    logger.info(f"Backfilling {len(symbols)} assets @ 4h / 730d...")
    rows = fetch_ohlcv(symbols, period="730d", interval="4h")
    if rows:
        n = upsert_ohlcv(conn, rows)
        logger.info(f"  → Upserted {n:,} rows (4h)")

    # 4. 1d (10 years)
    logger.info(f"Backfilling {len(symbols)} assets @ 1d / 10y...")
    rows = fetch_ohlcv(symbols, period="10y", interval="1d")
    if rows:
        n = upsert_ohlcv(conn, rows)
        logger.info(f"  → Upserted {n:,} rows (1d)")

    logger.info("=== Deep Backfill complete ===")


# ---------------------------------------------------------------------------
# Incremental refresh
# ---------------------------------------------------------------------------
def refresh_assets(conn, symbols: List[str]):
    """Fetch the latest 15m / 1h / 4h / 1d candles for tradeable symbols."""
    logger.info(f"Refreshing {len(symbols)} tradeable assets @ 15m, 1h, 4h, 1d...")

    for interval, period in [("15m", "2d"), ("1h", "7d"), ("4h", "14d"), ("1d", "30d")]:
        rows = fetch_ohlcv(symbols, period=period, interval=interval)
        if rows:
            n = upsert_ohlcv(conn, rows)
            logger.info(f"  {interval}: upserted {n:,} rows")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def _connect_with_retry(max_attempts: int = 30, sleep_fn=time.sleep):
    """Connect to PostgreSQL with bounded retries for startup races."""
    for attempt in range(max_attempts):
        try:
            conn = get_conn()
            logger.info("Connected to PostgreSQL")
            return conn
        except Exception as e:
            logger.warning(f"DB not ready (attempt {attempt+1}/{max_attempts}): {e}")
            sleep_fn(5)
    logger.error(f"Could not connect to PostgreSQL after {max_attempts} attempts. Exiting.")
    return None


def _run_refresh_cycle(conn, tickers: List[str], last_refresh: float, now: float | None = None) -> float:
    """Execute one polling decision and return the latest refresh timestamp."""
    now = time.time() if now is None else now
    if now - last_refresh >= MT5_POLL_INTERVAL:
        refresh_assets(conn, tickers)
        return now
    return last_refresh


def main():
    logger.info("=" * 60)
    logger.info("CryptoStream AI — yfinance Ingestion Service")
    logger.info(f"DB: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}")
    logger.info(f"Poll interval : {MT5_POLL_INTERVAL // 60} min")
    logger.info("=" * 60)

    TICKERS = _load_symbols()

    # Wait for DB to be ready (Docker startup race)
    conn = _connect_with_retry()
    if conn is None:
        return

    # One-time backfill on startup
    try:
        backfill(conn, TICKERS)
    except Exception as e:
        logger.error(f"Backfill error: {e}", exc_info=True)

    last_refresh = 0.0

    while True:
        now = time.time()
        try:
            last_refresh = _run_refresh_cycle(conn, TICKERS, last_refresh, now=now)

        except psycopg2.OperationalError:
            logger.warning("DB connection lost — reconnecting...")
            try:
                conn = get_conn()
            except Exception as e:
                logger.error(f"Reconnect failed: {e}")

        except Exception as e:
            logger.error(f"Refresh error: {e}", exc_info=True)

        # Sleep until next poll is due
        sleep_for = max(30, MT5_POLL_INTERVAL - (time.time() - last_refresh))
        logger.debug(f"Sleeping {sleep_for:.0f}s until next refresh...")
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
