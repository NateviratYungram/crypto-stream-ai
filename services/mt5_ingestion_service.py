"""
CryptoStream AI — MT5 Deep Ingestion Service
============================================
The 'Gold Standard' for data: pulls historical OHLCV directly from MT5 terminal.
Supports 10+ years of data for M15, H1, H4, and D1.
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import MetaTrader5 as mt5
import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("mt5_ingester")

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

# MT5 Timeframe Mapping
TF_MAP = {
    "15m": mt5.TIMEFRAME_M15,
    "1h":  mt5.TIMEFRAME_H1,
    "4h":  mt5.TIMEFRAME_H4,
    "1d":  mt5.TIMEFRAME_D1,
}

# Broker-specific Symbol Mapping (adjust if your broker uses suffixes like .xm, .m, etc.)
BROKER_SYMBOL_MAP = {
    "GOLD":   ["GOLD", "XAUUSD", "XAUUSD.m", "GOLD.m", "XAUUSD.xm"],
    "SILVER": ["SILVER", "XAGUSD", "XAGUSD.m", "SILVER.m", "XAGUSD.xm"],
    "BTCUSD": ["BTCUSD", "BTCUSD.m", "BTCUSD.xm", "BITCOIN"],
    "ETHUSD": ["ETHUSD", "ETHUSD.m", "ETHUSD.xm", "ETHEREUM"],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def init_mt5():
    """Initialize connection to MT5 terminal."""
    if not mt5.initialize():
        logger.error(f"MT5 initialize failed, error code: {mt5.last_error()}")
        return False
    
    account_info = mt5.account_info()
    if account_info:
        logger.info(f"Connected to MT5: {account_info.company} (Account: {account_info.login})")
    return True

def upsert_ohlcv(conn, rows: List[dict]) -> int:
    if not rows: return 0
    insert_sql = """
        INSERT INTO market_ohlcv (symbol, timeframe, ts, open, high, low, close, volume, source)
        VALUES %s
        ON CONFLICT (symbol, timeframe, ts) DO UPDATE
            SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, 
                close=EXCLUDED.close, volume=EXCLUDED.volume, fetched_at=NOW()
    """
    tuples = [(r["symbol"], r["timeframe"], r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"], "mt5") for r in rows]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, insert_sql, tuples, page_size=1000)
    conn.commit()
    return len(tuples)

# ---------------------------------------------------------------------------
# Deep Backfill
# ---------------------------------------------------------------------------
def backfill_symbol(conn, symbol: str, timeframe: str, years: int = 10, db_symbol: Optional[str] = None):
    """Fetch 'years' of data from MT5 for a specific symbol/tf."""
    mt5_tf = TF_MAP.get(timeframe)
    if mt5_tf is None: return

    target_symbol = db_symbol if db_symbol else symbol
    logger.info(f"Deep Backfill: {symbol} (as {target_symbol}) @ {timeframe} for {years} years...")
    
    # Calculate start time
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=365 * years)
    
    # Use copy_rates_from to avoid date parameter issues
    # rates = mt5.copy_rates_range(symbol, mt5_tf, start_naive, end_naive)
    
    # Approximate number of candles for 10 years
    count_map = {
        "15m": 20000, # Reduce to 20k to avoid 'Invalid params' or overflow
        "1h":  50000,
        "4h":  25000,
        "1d":  4000,
    }
    max_count = count_map.get(timeframe, 1000)

    # Fetch rates from current time backwards
    import time
    now_ts = int(time.time())
    rates = mt5.copy_rates_from(symbol, mt5_tf, now_ts, max_count)
    
    if rates is None or len(rates) == 0:
        logger.warning(f"  ! No data found for {symbol} ({mt5.last_error()})")
        return

    # Convert to dicts for DB
    rows = []
    for r in rates:
        rows.append({
            "symbol":    target_symbol,
            "timeframe": timeframe,
            "ts":        datetime.fromtimestamp(r['time'], tz=timezone.utc),
            "open":      float(r['open']),
            "high":      float(r['high']),
            "low":       float(r['low']),
            "close":     float(r['close']),
            "volume":    float(r['tick_volume']),
        })
    
    n = upsert_ohlcv(conn, rows)
    logger.info(f"  → Successfully upserted {n:,} rows")

def main():
    if not init_mt5(): return
    
    from intelligence.ml.signal_model import TRADE_TRAIN_SYMBOLS
    # Unique symbols and timeframes to backfill
    base_symbols = list(set([s[0] for s in TRADE_TRAIN_SYMBOLS]))
    tfs = ["15m", "1h", "4h", "1d"]
    
    conn = get_conn()
    
    logger.info("=" * 60)
    logger.info(f"STARTING 10-YEAR BIG DATA INGESTION (MT5)")
    logger.info("=" * 60)
    
    for base_sym in base_symbols:
        # Try to find the correct symbol name for this broker
        possible_names = BROKER_SYMBOL_MAP.get(base_sym, [base_sym])
        actual_sym = None
        
        for name in possible_names:
            symbol_info = mt5.symbol_info(name)
            if symbol_info is not None:
                actual_sym = name
                break
        
        if actual_sym is None:
            logger.warning(f"Symbol {base_sym} not found in MT5 (tried {possible_names}). Skipping.")
            continue
            
        logger.info(f"Using broker symbol: {actual_sym} for {base_sym}")
        
        if not mt5.symbol_select(actual_sym, True):
            logger.warning(f"Failed to select {actual_sym}. Skipping.")
            continue

        for tf in tfs:
            try:
                # We still store in DB using the 'base_sym' (like GOLD) for consistency
                backfill_symbol(conn, actual_sym, tf, years=10, db_symbol=base_sym)
            except Exception as e:
                logger.error(f"Error backfilling {actual_sym} {tf}: {e}")
                
    logger.info("=" * 60)
    logger.info("BIG DATA INGESTION COMPLETE")
    logger.info("=" * 60)
    
    mt5.shutdown()
    conn.close()

if __name__ == "__main__":
    main()
