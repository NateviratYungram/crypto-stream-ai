import logging
import sqlite3
import time
from contextlib import closing
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

ARCHIVE_DB = "market_archive.sqlite"

class IntelligenceArchiver:
    """
    Manages the Institutional SQL Archive for OHLCV data.
    Provides millisecond retrieval and persistent storage.
    """
    def __init__(self, db_path: str = ARCHIVE_DB):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initializes the SQLite schema with optimized indexing."""
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ohlcv_archive (
                        symbol TEXT,
                        timeframe TEXT,
                        datetime TEXT,
                        open REAL,
                        high REAL,
                        low REAL,
                        close REAL,
                        volume REAL,
                        PRIMARY KEY (symbol, timeframe, datetime)
                    )
                """)
                # Index for fast range scans
                cur.execute("CREATE INDEX IF NOT EXISTS idx_sym_tf ON ohlcv_archive (symbol, timeframe, datetime DESC)")
                conn.commit()
        except Exception as e:
            logger.error(f"Archiver: DB Init failed: {e}")

    def save_data(self, symbol: str, timeframe: str, df: pd.DataFrame):
        """Upserts a DataFrame into the archive."""
        if df is None or df.empty:
            return
        try:
            # Standardize column naming for SQLite
            df_sql = df.copy()
            if "Datetime" in df_sql.columns:
                df_sql["datetime"] = df_sql["Datetime"].astype(str)
            else:
                df_sql["datetime"] = df_sql.index.astype(str)

            df_sql["symbol"] = symbol.upper()
            df_sql["timeframe"] = timeframe

            # Prepare for upsert
            with closing(sqlite3.connect(self.db_path)) as conn:
                for _, row in df_sql.iterrows():
                    conn.execute("""
                        INSERT INTO ohlcv_archive (symbol, timeframe, datetime, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(symbol, timeframe, datetime) DO UPDATE SET
                            open=excluded.open, high=excluded.high, low=excluded.low,
                            close=excluded.close, volume=excluded.volume
                    """, (
                        row["symbol"], row["timeframe"], row["datetime"],
                        row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
                    ))
                conn.commit()
            logger.info(f"Archiver: Saved {len(df)} bars for {symbol} ({timeframe})")
        except Exception as e:
            logger.error(f"Archiver: Save failed for {symbol}: {e}")

    def get_data(self, symbol: str, timeframe: str, limit: int = 2000) -> Optional[pd.DataFrame]:
        """Retrieves cached data from SQL in milliseconds."""
        try:
            query = """
                SELECT datetime as Datetime, open as Open, high as High, low as Low, close as Close, volume as Volume
                FROM ohlcv_archive
                WHERE symbol = ? AND timeframe = ?
                ORDER BY datetime DESC
                LIMIT ?
            """
            with closing(sqlite3.connect(self.db_path)) as conn:
                df = pd.read_sql_query(query, conn, params=(symbol.upper(), timeframe, limit))

            if df.empty:
                return None

            # Restore expected format
            df["Datetime"] = pd.to_datetime(df["Datetime"])
            df = df.sort_values("Datetime").reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"Archiver: Fetch failed for {symbol}: {e}")
            return None

    def bootstrap_history(self, symbol: str, asset_class: str = "MACRO", timeframe: str = "1d", years: int = 10):
        """
        Maximizes historical depth. Uses pagination for Crypto (Binance)
        and max-period fetches for Macro (yfinance).
        """

        logger.info(f"Archiver: Deep-Crawl started for {symbol} ({timeframe}) Target: {years}y")

        if asset_class == "CRYPTO":
            return self._deep_crawl_binance(symbol, timeframe, years)
        else:
            return self._deep_crawl_yfinance(symbol, timeframe, years)

    def _deep_crawl_binance(self, symbol: str, timeframe: str, years: int):
        """Crawls Binance backwards until 10 years or max depth reached."""
        sym = symbol.upper().replace("USDT", "") + "USDT"
        limit_per_req = 1000
        interval = timeframe # e.g. '1h', '15m'

        end_time = int(time.time() * 1000)
        start_target = end_time - (years * 365 * 24 * 60 * 60 * 1000)

        total_synced = 0
        current_end = end_time

        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                while current_end > start_target:
                    url = "https://api.binance.com/api/v3/klines"
                    # For Binance, we usually crawl forwards or backwards.
                    # Let's crawl forwards from the target for simplicity in bulk insert.
                    params = {
                        "symbol": sym,
                        "interval": interval,
                        "startTime": start_target,
                        "limit": limit_per_req
                    }
                    r = requests.get(url, params=params, timeout=10)
                    if r.status_code != 200:
                        break

                    raw = r.json()
                    if not raw or not isinstance(raw, list):
                        break

                    # Convert to DF
                    df = pd.DataFrame(raw, columns=[
                        "ot","Open","High","Low","Close","Volume","ct","qav","tr","tbav","tqav","i"
                    ])
                    df["datetime"] = pd.to_datetime(df["ot"], unit="ms").astype(str)

                    # Batch Upsert
                    data = []
                    for _, row in df.iterrows():
                        data.append((
                            symbol.upper(), timeframe, row["datetime"],
                            float(row["Open"]), float(row["High"]), float(row["Low"]),
                            float(row["Close"]), float(row["Volume"])
                        ))

                    conn.executemany("""
                        INSERT INTO ohlcv_archive (symbol, timeframe, datetime, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(symbol, timeframe, datetime) DO UPDATE SET
                            open=excluded.open, high=excluded.high, low=excluded.low,
                            close=excluded.close, volume=excluded.volume
                    """, data)

                    last_time = raw[-1][0]
                    if last_time >= current_end or len(raw) < limit_per_req:
                        break # Reached end of available data

                    start_target = last_time + 1 # Move window forward
                    total_synced += len(raw)
                    logger.info(f"Archiver: {symbol} Syncing... {total_synced} bars")
                    time.sleep(0.1) # Respect rate limits

                conn.commit()
            return total_synced
        except Exception as e:
            logger.error(f"Archiver: Binance Crawl failed for {symbol}: {e}")
            return total_synced

    def _deep_crawl_yfinance(self, symbol: str, timeframe: str, years: int):
        """Maximizes yfinance fetch for Macro assets."""
        from intelligence.technical_engine import get_kline_data

        # yfinance period mapping
        period = "10y" if years <= 10 else "max"
        if timeframe in ["15m", "30m", "1h"]:
            period = "2y" # yfinance limit for intraday

        logger.info(f"Archiver: yfinance Max-Fetch for {symbol} ({timeframe}) Period: {period}")
        df = get_kline_data(symbol, timeframe=timeframe, limit=50000, asset_class="MACRO")

        if df is not None and not df.empty:
            self.save_data(symbol, timeframe, df)
            return len(df)
        return 0

# Global instance for shared use
archiver = IntelligenceArchiver()
