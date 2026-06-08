import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine, text

from intelligence.archiver import archiver
from intelligence.constants import (
    MACRO_MAPPING,
    NASDAQ_100_TICKERS,
    SP500_TICKERS,
    TICKER_ALIASES,
    YFINANCE_DISABLED_TICKERS,
)
from intelligence.mt5_connector import (
    _MT5_AVAILABLE,
    mt5_get_rates,
)

# Configure yfinance cache to avoid disk I/O errors in restricted environments
try:
    cache_dir = os.path.join(os.getcwd(), ".yf_cache")
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)
    yf.set_tz_cache_location(cache_dir)
except Exception:
    pass

logger = logging.getLogger(__name__)


def _utcnow_aware() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_naive() -> datetime:
    return _utcnow_aware().replace(tzinfo=None)

# ── Timeframe → seconds mapping (used for PostgreSQL bucket queries) ──────────
TIMEFRAME_SECONDS = {
    "1m":  60,
    "5m":  300,
    "15m": 900,
    "1h":  3600,
    "4h":  14400,
    "1d":  86400,
}

# ── Hurst Exponent (R/S Analysis) helper ──────────────────────────────────
def compute_hurst_exponent(ts: pd.Series, window: int = 100) -> float:
    """
    Calculates the Hurst Exponent using Rescaled Range (R/S) analysis on a rolling window.
    H < 0.5: Mean Reverting (anti-persistent)
    H = 0.5: Random Walk (GBM)
    H > 0.5: Trending (persistent)
    """
    if len(ts) < window:
        return 0.5

    try:
        data = ts.values[-window:]
        # Subtract mean to get residuals
        res = data - np.mean(data)
        # Cumulative sum of residuals
        cum_res = np.cumsum(res)
        # Range
        R = np.max(cum_res) - np.min(cum_res)
        # Standard deviation
        S = np.std(data)
        if S == 0:
            return 0.5

        # Simple H estimate for rolling window
        H = np.log(R/S) / np.log(window)
        return float(np.clip(H, 0.0, 1.0))
    except Exception:
        return 0.5

# ── SQLAlchemy engine factory (singleton, lazy-init) ─────────────────────────
_pg_engine = None

_last_pg_engine_fail = 0

def _get_pg_engine():
    """Return a cached SQLAlchemy engine for crypto_stream_db with failure caching."""
    global _pg_engine, _last_pg_engine_fail
    import time

    if time.time() - _last_pg_engine_fail < 60:
        return None

    if _pg_engine is None:
        try:
            host = os.getenv("DB_HOST", "localhost")
            port = os.getenv("DB_PORT", "5432")
            db   = os.getenv("DB_NAME", "crypto_stream_db")
            user = os.getenv("DB_USER", "user")
            pw   = os.getenv("DB_PASS", "password")

            _pg_engine = create_engine(
                f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{db}",
                pool_pre_ping=True,
                pool_size=3,
                max_overflow=2,
                connect_args={"connect_timeout": 1},
            )
            # Test connection once
            with _pg_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            _last_pg_engine_fail = time.time()
            _pg_engine = None
            return None

    return _pg_engine

# ── DB-first lookup for market_ohlcv (Stocks / Macro) ────────────────────────
# How fresh data must be before we skip the DB and call yfinance live.
_FRESHNESS_SECONDS = {
    "1m":  120,    # 2 min stale → fetch live
    "5m":  600,    # 10 min
    "15m": 1200,   # 20 min
    "1h":  3600,   # 1 hour
    "1d":  43200,  # 12 hours (daily candle)
}


def _is_dataframe_fresh(df: Optional[pd.DataFrame], timeframe: str) -> bool:
    """Return True when the latest candle is fresh enough for live analysis."""
    try:
        if df is None or df.empty or "Datetime" not in df.columns:
            return False
        freshness = _FRESHNESS_SECONDS.get(timeframe, 1200)
        latest = pd.to_datetime(df["Datetime"].max(), utc=True)
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=freshness)
        return latest >= cutoff
    except Exception:
        return False

def _query_market_ohlcv(ticker: str, timeframe: str, limit: int, ignore_freshness: bool = False) -> Optional[pd.DataFrame]:
    """
    Try to serve OHLCV from the market_ohlcv table.
    Returns a DataFrame ready for compute_indicators(), or None on miss/stale.
    """
    try:
        engine = _get_pg_engine()
        if engine is None:
            return None

        sql = text("""
            SELECT ts AS "Datetime", open AS "Open", high AS "High",
                   low AS "Low", close AS "Close", volume AS "Volume"
            FROM   market_ohlcv
            WHERE  symbol    = :sym
              AND  timeframe = :tf
            ORDER  BY ts DESC
            LIMIT  :lim
        """)
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={"sym": ticker, "tf": timeframe, "lim": limit})

        if df.empty or len(df) < 5:
            return None

        # Sort values so indicators work correctly (must be chronological)
        df = df.sort_values("Datetime").reset_index(drop=True)
        df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True).dt.tz_localize(None)

        if not ignore_freshness:
            freshness = _FRESHNESS_SECONDS.get(timeframe, 1200)
            cutoff = _utcnow_naive() - timedelta(seconds=freshness)
            latest = df["Datetime"].max()
            if latest < cutoff:
                logger.info(f"market_ohlcv cache STALE for {ticker}/{timeframe} (latest={latest})")
                return None

        logger.info(f"market_ohlcv cache HIT for {ticker}/{timeframe} ({len(df)} rows)")
        return df[["Datetime", "Open", "High", "Low", "Close", "Volume"]]

    except Exception as e:
        logger.warning(f"market_ohlcv query failed for {ticker}/{timeframe}: {e}")
        return None

# ── Macro Asset Mapping (Yahoo Finance Tickers) ──────────────────────────────
# Asset mappings now managed in intelligence/constants.py

def get_kline_data(
    symbol: str,
    timeframe: str = "15m",
    limit: int = 60,
    asset_class: str = "CRYPTO",
    ignore_freshness: bool = False
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV data. Pulls from PostgreSQL if it's a tracked Crypto asset,
    otherwise falls back to yfinance for Macro/Stock data.
    """
    sym = symbol.upper().replace("USDT", "").strip()

    # ── Choice 0: MT5 Data Bridge (Highest Priority for Real-Time Sync) ──
    # Check MT5 with the RAW symbol before any alias mappings occur
    force_mt5_history = os.getenv("ML_TRAIN_USE_MT5", "0").strip().lower() in {"1", "true", "yes"}
    if _MT5_AVAILABLE and (not ignore_freshness or force_mt5_history):
        try:
            mt5_rates = mt5_get_rates(sym, timeframe=timeframe, count=limit)
            if mt5_rates is not None and not mt5_rates.empty:
                logger.info(f"TechnicalEngine: MT5 sync HIT for {sym}/{timeframe}")
                mt5_rates.attrs["market_status"] = "OPEN"
                mt5_rates.attrs["last_update"] = _utcnow_aware().isoformat()
                return mt5_rates
        except Exception as e_mt5:
            logger.warning(f"TechnicalEngine: MT5 raw sync attempt failed for {sym}: {e_mt5}")

    # ── Choice A: PostgreSQL Cache (Macro/Stock/Crypto) ──
    # Check if we have this in market_ohlcv (Deep History)
    db_df = _query_market_ohlcv(sym, timeframe, limit, ignore_freshness=ignore_freshness)
    if db_df is not None:
        return db_df

    _sym_crypto = sym  # save pre-alias for Binance/Postgres queries

    # Apply global alias map first (TSMC→TSM, TSLA stays TSLA, etc.)
    sym = TICKER_ALIASES.get(sym, sym)

    # Strip -USD suffix for crypto routing logic (but keep it for yfinance lookup)
    _sym_no_usd = sym.replace("-USD", "").replace("USD", "").strip()

    # ── Choice A: Macro / Stock Assets (yfinance) ─────────────────────────────
    # Standardize common aliases
    GOLD_ALIASES = {"GOLD", "XAU", "XAUUSD", "XAUSD", "GC=F"}
    KNOWN_CRYPTO = {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOGE",
                    "MATIC", "DOT", "LINK", "UNI", "LTC", "ATOM", "NEAR", "OP",
                    "ARB", "APT", "SUI", "TRX", "TON", "PEPE", "SHIB"}

    if sym in GOLD_ALIASES:
        sym = "GC=F"  # Gold Futures — more reliable on yfinance than XAUUSD=X (Forex spot)

    is_macro = (
        asset_class in ("STOCK", "MACRO") or
        sym in MACRO_MAPPING or
        sym in NASDAQ_100_TICKERS or
        sym in SP500_TICKERS or
        sym.startswith("^") or
        sym.endswith("=F") or
        # Any ticker that is NOT a known crypto → treat as stock/equity via yfinance
        (sym not in KNOWN_CRYPTO and asset_class not in ("CRYPTO",) and
         not symbol.upper().endswith("USDT"))
    )
    if is_macro:
        ticker = MACRO_MAPPING.get(sym, sym)
        # Ensure ticker is standard for common names
        if ticker in ("GOLD", "XAUUSD=X"):
            ticker = "GC=F"
        if ticker == "NASDAQ":
            ticker = "^IXIC"
        if ticker == "SP500":
            ticker = "^GSPC"
        if ticker in YFINANCE_DISABLED_TICKERS:
            logger.info(f"TechnicalEngine: yfinance disabled for known no-data ticker {ticker}")
            df_disabled = pd.DataFrame([{
                "Datetime": _utcnow_naive(),
                "Open": 0.0,
                "High": 0.0,
                "Low": 0.0,
                "Close": 0.0,
                "Volume": 0,
                "is_speculative": True,
                "target_symbol": ticker,
            }])
            df_disabled.attrs["market_status"] = "NO_DATA"
            df_disabled.attrs["last_update"] = _utcnow_aware().isoformat()
            return df_disabled


        # ── Choice 1: Archive SQL (High-Speed Historical Cache) ────────────────
        try:
            cached_sql = archiver.get_data(ticker, timeframe, limit=limit)
            if cached_sql is not None and len(cached_sql) >= limit:
                if ignore_freshness or _is_dataframe_fresh(cached_sql, timeframe):
                    logger.info(f"TechnicalEngine: SQL Archive HIT for {ticker}/{timeframe}")
                    return cached_sql
                latest = pd.to_datetime(cached_sql["Datetime"].max(), utc=True)
                logger.info(f"TechnicalEngine: SQL Archive STALE for {ticker}/{timeframe} (latest={latest})")
        except Exception as e_sql:
            logger.warning(f"TechnicalEngine: SQL Archive fetch failed for {ticker}: {e_sql}")

        # ── Choice 2: DB-first (Original market_ohlcv) ────────────────────────
        cached = _query_market_ohlcv(ticker, timeframe, limit)
        if cached is not None:
            return cached

        logger.info(f"TechnicalEngine: SQL miss — fetching live from yfinance for {ticker}...")

        # ... (yfinance fetch logic continues) ...

        # Map timeframe to yfinance intervals and appropriate period
        # 1d → "max" gives 20+ years; 1h → "730d" gives 2 years (yfinance cap)
        # 15m → "60d" is the yfinance hard cap for sub-hour intervals
        yf_intervals = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "1d": "1d"}
        interval = yf_intervals.get(timeframe, "1d")
        period_map = {
            "1m":  "5d",
            "5m":  "60d",
            "15m": "60d",
            "1h":  "730d",
            "4h":  "730d",
            "1d":  "max",
        }
        period = period_map.get(timeframe, "60d")

        try:
            df_yf = yf.download(
                ticker, period=period, interval=interval,
                progress=False, group_by="ticker"
            )

            if df_yf.empty:
                # Retry with daily interval + 1y period (covers weekends, holidays, illiquid tickers)
                logger.warning(f"TechnicalEngine: yfinance empty for {ticker}, retrying 1d/1y")
                df_yf = yf.download(ticker, period="1y", interval="1d",
                                    progress=False, group_by="ticker")

            if df_yf.empty:
                logger.warning(f"TechnicalEngine: No data found for {ticker}")
                return pd.DataFrame([{
                    "Datetime": _utcnow_naive(),
                    "Open": 0.0, "High": 0.0, "Low": 0.0, "Close": 0.0, "Volume": 0,
                    "is_speculative": True,
                    "target_symbol": ticker
                }])

            # ── Fix: Handle MultiIndex / Symbol level extraction ──────────────────
            if isinstance(df_yf.columns, pd.MultiIndex):
                levels = df_yf.columns.get_level_values(0).unique().tolist()
                # yfinance ≥0.2.x: (Price, Ticker) — flatten to Price level
                if ticker in df_yf.columns.get_level_values(-1).unique().tolist():
                    # Ticker is at the LAST level → select it
                    df_yf = df_yf.xs(ticker, axis=1, level=-1)
                elif ticker in levels:
                    df_yf = df_yf[ticker]
                else:
                    # Just flatten whatever the first level is
                    df_yf.columns = df_yf.columns.get_level_values(0)


            df_yf = df_yf.tail(limit).reset_index()

            # Normalize column names
            df_yf = df_yf.rename(columns={
                "Date": "Datetime",
                "Adj Close": "Close_Adj"
            })

            # Use Adj Close if it exists and is valid, otherwise regular Close
            if "Close_Adj" in df_yf.columns:
                df_yf["Close"] = df_yf["Close_Adj"]

            if "Datetime" not in df_yf.columns and "Date" in df_yf.columns:
                 df_yf = df_yf.rename(columns={"Date": "Datetime"})

            # Fill missing required columns with NAs or zeros if they don't exist
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                if col not in df_yf.columns:
                    df_yf[col] = np.nan

            # Strip timezone so ta/pandas-ta indicators don't fail on tz-aware datetimes
            if "Datetime" in df_yf.columns:
                try:
                    df_yf["Datetime"] = df_yf["Datetime"].dt.tz_localize(None)
                except Exception:
                    try:
                        df_yf["Datetime"] = df_yf["Datetime"].dt.tz_convert(None)
                    except Exception:
                        pass

            # ── Market Status Detection ───────────────────────────────────────
            # Logic: If latest candle is > 4x timeframe stale, market is likely closed.
            try:
                latest_ts = pd.to_datetime(df_yf["Datetime"].iloc[-1], utc=True)
                # Ensure UTC for comparison
                now_ts = _utcnow_aware().astimezone(latest_ts.tzinfo)
                diff_mins = (now_ts - latest_ts).total_seconds() / 60

                tf_mins = TIMEFRAME_SECONDS.get(timeframe, 60) / 60
                market_status = "OPEN"
                if diff_mins > (tf_mins * 4):
                    market_status = "CLOSED"

                df_yf.attrs["market_status"] = market_status
                df_yf.attrs["last_update"] = latest_ts.isoformat()
            except Exception:
                df_yf.attrs["market_status"] = "UNKNOWN"

            # Save to SQL Archive for future millisecond retrieval
            try:
                archiver.save_data(ticker, timeframe, df_yf)
            except Exception as e_save:
                logger.warning(f"TechnicalEngine: SQL Archiver save failed for {ticker}: {e_save}")

            return df_yf[["Datetime", "Open", "High", "Low", "Close", "Volume"]]
        except Exception as e:
            logger.error(f"TechnicalEngine: yfinance error for {ticker}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    # ── Choice B: Crypto Assets (PostgreSQL) ──────────────────────────────────
    pg_sym = _sym_crypto + "USDT"  # use pre-alias symbol (BTC not BTC-USD)
    tf_secs = TIMEFRAME_SECONDS.get(timeframe, 900)
    MAX_LOOKBACK_S = 86400 * 365 * 20  # cap at 20 years to prevent timedelta overflow
    lookback_s = min(limit * tf_secs * 2, MAX_LOOKBACK_S)
    since = _utcnow_naive() - timedelta(seconds=lookback_s)

    sql_live = f"""
        SELECT
            (timestamp / 1000 / {tf_secs}) * {tf_secs} AS bucket_epoch,
            to_timestamp((timestamp / 1000 / {tf_secs}) * {tf_secs}) AT TIME ZONE 'UTC' AS bucket_time,
            (array_agg(price ORDER BY timestamp ASC))[1]   AS open,
            MAX(price)                                      AS high,
            MIN(price)                                      AS low,
            (array_agg(price ORDER BY timestamp DESC))[1]  AS close,
            SUM(quantity)                                   AS volume
        FROM enriched_trades
        WHERE symbol = %s AND timestamp >= %s
        GROUP BY bucket_epoch, bucket_time
        ORDER BY bucket_time ASC
        LIMIT %s
    """

    sql_fallback = f"""
        SELECT * FROM (
            SELECT
                (timestamp / 1000 / {tf_secs}) * {tf_secs} AS bucket_epoch,
                to_timestamp((timestamp / 1000 / {tf_secs}) * {tf_secs}) AT TIME ZONE 'UTC' AS bucket_time,
                (array_agg(price ORDER BY timestamp ASC))[1]   AS open,
                MAX(price)                                      AS high,
                MIN(price)                                      AS low,
                (array_agg(price ORDER BY timestamp DESC))[1]  AS close,
                SUM(quantity)                                   AS volume
            FROM enriched_trades
            WHERE symbol = %s
            GROUP BY bucket_epoch, bucket_time
            ORDER BY bucket_epoch DESC
            LIMIT %s
        ) sub
        ORDER BY bucket_epoch ASC
    """

    df = pd.DataFrame()
    try:
        engine = _get_pg_engine()
        with engine.connect() as conn:
            df = pd.read_sql(sql_live, conn, params=(pg_sym, int(since.timestamp() * 1000), limit))
            if df.empty or len(df) < (limit * 0.5):
                df = pd.read_sql(sql_fallback, conn, params=(pg_sym, limit))
    except Exception as e:
        logger.warning(f"TechnicalEngine: DB unavailable for {pg_sym} ({e}) — trying Binance public API")

    if df.empty or len(df) < 5:
        # ── Binance public klines fallback (no key required) ─────────────────
        try:
            import requests as _req
            bf_interval = {"1m":"1m","5m":"5m","15m":"15m","1h":"1h","4h":"4h","1d":"1d"}.get(timeframe, "15m")
            r = _req.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": pg_sym, "interval": bf_interval, "limit": min(limit, 1000)},
                timeout=10,
            )
            if r.status_code == 200:
                raw = r.json()
                if isinstance(raw, list) and len(raw) >= 5:
                    df_b = pd.DataFrame(raw, columns=[
                        "open_time","Open","High","Low","Close","Volume",
                        "close_time","quote_vol","trades","taker_base","taker_quote","ignore"
                    ])
                    # Use timezone-naive UTC so ta/pandas-ta don't raise tz errors
                    df_b["Datetime"] = pd.to_datetime(df_b["open_time"], unit="ms", utc=True).dt.tz_localize(None)
                    for col in ("Open","High","Low","Close","Volume"):
                        df_b[col] = pd.to_numeric(df_b[col], errors="coerce")
                    df_b = df_b.dropna(subset=["Open","High","Low","Close"]).reset_index(drop=True)
                    if len(df_b) >= 5:
                        logger.info(f"TechnicalEngine: Binance fallback OK for {pg_sym} ({len(df_b)} bars)")
                        return df_b[["Datetime","Open","High","Low","Close","Volume"]]
        except Exception as be:
            logger.warning(f"TechnicalEngine: Binance fallback failed ({be}) — trying yfinance")
        # ── yfinance last-resort: pass raw sym so MACRO_MAPPING resolves BTC→BTC-USD ──
        logger.warning(f"TechnicalEngine: No data in Postgres for {pg_sym} → yfinance last resort")
        return get_kline_data(sym, timeframe, limit, "STOCK")

    df = df.rename(columns={
        "bucket_time": "Datetime",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    })

    for col in ("Open", "High", "Low", "Close", "Volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Open", "High", "Low", "Close"]).reset_index(drop=True)
    df["Datetime"] = pd.to_datetime(df["Datetime"])
    return df[["Datetime", "Open", "High", "Low", "Close", "Volume"]]


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add all technical indicators to a OHLCV DataFrame using ta library.

    Indicators added:
        rsi_14, macd, macd_signal, macd_hist,
        stoch_k, stoch_d, willr_14, roc_10,
        adx_14, atr_14, bb_upper, bb_mid, bb_lower,
        ema_20, ema_50
    """
    try:
        import ta
    except ImportError:
        logger.error("ta not installed. Run: pip install ta")
        return df

    df = df.copy()
    c = df["Close"]
    h = df["High"]
    low_series = df["Low"]

    # RSI
    df["rsi_14"] = ta.momentum.RSIIndicator(close=c, window=14).rsi()

    # MACD
    macd = ta.trend.MACD(close=c, window_slow=26, window_fast=12, window_sign=9)
    df["macd"]        = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"]   = macd.macd_diff()

    # Stochastic
    stoch = ta.momentum.StochasticOscillator(
        high=h,
        low=low_series,
        close=c,
        window=14,
        smooth_window=3,
    )
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    # Williams %R
    df["willr_14"] = ta.momentum.WilliamsRIndicator(
        high=h,
        low=low_series,
        close=c,
        lbp=14,
    ).williams_r()

    # Rate of Change
    df["roc_10"] = ta.momentum.ROCIndicator(close=c, window=10).roc()

    # ADX (Average Directional Index)
    adx = ta.trend.ADXIndicator(high=h, low=low_series, close=c, window=14)
    df["adx_14"] = adx.adx()

    # ATR
    df["atr_14"] = ta.volatility.AverageTrueRange(high=h, low=low_series, close=c, window=14).average_true_range()

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(close=c, window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_mid"]   = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()

    # EMA
    df["ema_20"] = ta.trend.EMAIndicator(close=c, window=20).ema_indicator()
    df["ema_50"] = ta.trend.EMAIndicator(close=c, window=50).ema_indicator()
    df["ema_200"] = ta.trend.EMAIndicator(close=c, window=200).ema_indicator()

    # Volume indicators
    if "Volume" in df.columns:
        v = df["Volume"]
        df["volume_sma_20"] = v.rolling(window=20).mean()
        # Chaikin Money Flow (CMF) — measure of accumulation/distribution
        df["cmf_20"] = ta.volume.ChaikinMoneyFlowIndicator(
            high=h,
            low=low_series,
            close=c,
            volume=v,
            window=20,
        ).chaikin_money_flow()

    # ── Intelligence V6: Advanced Alpha Core ────────────────────────────────
    # 1. Relative Volatility Index (RVI)
    # Measures the direction of volatility (Standard Deviation-based RSI)
    def compute_rvi(close_series, window=14):
        std = close_series.diff().rolling(window=10).std()
        up = std.where(close_series.diff() > 0, 0.0)
        dn = std.where(close_series.diff() < 0, 0.0)
        avg_up = up.rolling(window=window).mean()
        avg_dn = dn.rolling(window=window).mean()
        return 100 * avg_up / (avg_up + avg_dn)

    df["rvi_14"] = compute_rvi(df["Close"])

    # ── Intelligence V5: Hurst Exponent (Trend Persistence) ─────────────────
    # Window=100 (primary regime), Window=30 (scalping bias)
    df["hurst_100"] = df["Close"].rolling(window=100).apply(lambda x: compute_hurst_exponent(x, 100))
    df["hurst_30"]  = df["Close"].rolling(window=30).apply(lambda x: compute_hurst_exponent(x, 30))

    # ── VWAP (Volume Weighted Average Price) — key institutional level ────────
    if "Volume" in df.columns and df["Volume"].sum() > 0:
        typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
        df["vwap"] = (typical_price * df["Volume"]).cumsum() / df["Volume"].cumsum()

    return df


def get_indicator_summary(df: pd.DataFrame, symbol: str = "") -> dict:
    """
    Extract the latest indicator values as a clean dict for use in prompts.

    Returns:
        dict with latest values for each indicator + simple signal labels
    """
    if df.empty:
        return {}

    # ── Handle Speculative Mode (Empty Data Fallback) ──────────────────────────
    if "is_speculative" in df.columns and df.iloc[0].get("is_speculative"):
        target = df.iloc[0].get("target_symbol", symbol)
        return {
            "symbol": target,
            "status": "SPECULATIVE_MODE",
            "reason": "Indicator data temporarily unavailable for this ticker.",
            "instruction": "Analyze based on current market sentiment or price action from external charts. Provide 6-part trade plan."
        }

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    def safe(val, default=0.0):
        try:
            v = float(val)
            return round(v, 4) if not np.isnan(v) else default
        except (TypeError, ValueError):
            return default

    rsi = safe(last.get("rsi_14"))
    macd_val = safe(last.get("macd"))
    macd_prev = safe(prev.get("macd"))
    macd_hist = safe(last.get("macd_hist"))
    macd_hist_prev = safe(prev.get("macd_hist"))
    stoch_k = safe(last.get("stoch_k"))
    stoch_d = safe(last.get("stoch_d"))
    willr = safe(last.get("willr_14"))
    roc = safe(last.get("roc_10"))
    adx = safe(last.get("adx_14"))
    atr = safe(last.get("atr_14"))
    close = safe(last.get("Close"))
    bb_upper = safe(last.get("bb_upper"))
    bb_lower = safe(last.get("bb_lower"))
    ema_20 = safe(last.get("ema_20"))
    ema_50 = safe(last.get("ema_50"))
    ema_200 = safe(last.get("ema_200"))
    volume = safe(last.get("Volume"))
    vol_sma = safe(last.get("volume_sma_20"))
    cmf = safe(last.get("cmf_20"))
    rvi = safe(last.get("rvi_14"))
    hurst_100 = safe(last.get("hurst_100"), 0.5)
    hurst_30 = safe(last.get("hurst_30"), 0.5)
    vwap = safe(last.get("vwap"))

    # Signal labels
    rsi_signal = (
        "Overbought (>70)" if rsi > 70 else
        "Oversold (<30)"   if rsi < 30 else
        "Neutral"
    )
    macd_signal = (
        "Bullish Crossover" if macd_val > 0 and macd_prev <= 0 else
        "Bearish Crossover" if macd_val < 0 and macd_prev >= 0 else
        "Bullish"           if macd_val > 0 else
        "Bearish"
    )
    hist_signal = (
        "Increasing (Momentum UP)"   if macd_hist > macd_hist_prev else
        "Decreasing (Momentum DOWN)"
    )
    stoch_signal = (
        "Overbought"  if stoch_k > 80 else
        "Oversold"    if stoch_k < 20 else
        "Neutral"
    )
    willr_signal = (
        "Overbought"  if willr > -20 else
        "Oversold"    if willr < -80 else
        "Neutral"
    )
    trend_strength = (
        "Strong Trend"       if adx > 25 else
        "Weak/No Trend"      if adx < 20 else
        "Transitioning"
    )
    bb_signal = (
        "Above Upper Band (Overbought)" if close > bb_upper else
        "Below Lower Band (Oversold)"   if close < bb_lower else
        "Inside Bands"
    )
    ema_signal = (
        "Bullish (Price > EMA20 > EMA50)" if close > ema_20 > ema_50 else
        "Bearish (Price < EMA20 < EMA50)" if close < ema_20 < ema_50 else
        "Mixed"
    )
    long_term_trend = (
        "BULLISH" if close > ema_200 else "BEARISH"
    )
    volume_spike = volume > (vol_sma * 1.5) if vol_sma > 0 else False

    # Safe extraction of Patterns and Trend (Wrapped in Try-Except for Robustness)
    patterns_data = {"detected": ["None"], "observation": "Analysis pending"}
    trend_data = {"status": "Analysis pending"}

    try:
        patterns_data = detect_patterns(df)
    except Exception as e:
        logger.error(f"TechnicalEngine: Error in detect_patterns: {e}")

    try:
        trend_data = analyze_trend_channels(df)
    except Exception as e:
        logger.error(f"TechnicalEngine: Error in analyze_trend_channels: {e}")

    # Hurst Interpretation
    hurst_regime = (
        "Strong Trend (Persistent)" if hurst_100 > 0.55 else
        "Mean Reverting (Anti-Persistent)" if hurst_100 < 0.45 else
        "Random Walk (No Signal Edge)"
    )

    summary = {
        "symbol":    symbol,
        "price":     close,
        "rsi":       {"value": rsi, "signal": rsi_signal},
        "macd":      {"value": macd_val, "signal": macd_signal},
        "macd_histogram": {"value": macd_hist, "signal": hist_signal},
        "stochastic": {"k": stoch_k, "d": stoch_d, "signal": stoch_signal},
        "williams_r": {"value": willr, "signal": willr_signal},
        "roc": {"value": roc, "description": "Rate of Change 10-period"},
        "adx": {"value": adx, "signal": trend_strength},
        "atr": {"value": atr, "description": "Average True Range (volatility)"},
        "bollinger_bands": {
            "upper": bb_upper, "lower": bb_lower,
            "position": bb_signal
        },
        "ema": {"ema_20": ema_20, "ema_50": ema_50, "ema_200": ema_200, "signal": ema_signal, "long_term": long_term_trend},
        "volume": {"value": volume, "sma_20": vol_sma, "spike": volume_spike, "cmf": cmf},
        "vwap": {"value": vwap, "position": "Above VWAP (Bullish)" if close > vwap > 0 else "Below VWAP (Bearish)" if vwap > 0 else "N/A"},
        "volatility": {"atr": atr, "rvi": rvi},
        "hurst": {"h100": hurst_100, "h30": hurst_30, "regime": hurst_regime},
        "patterns": patterns_data,
        "trend_analysis": trend_data,
        "timestamp": _utcnow_aware().isoformat()
    }

    return summary

def detect_patterns(df: pd.DataFrame) -> dict:
    """
    Advanced Pattern Recognition Agent (Inspired by QuantAgent).
    Detects Candle Patterns and Price Formations.
    """
    # Just-in-time check for enough data
    if df is None or len(df) < 5:
        return {"detected": ["None"], "observation": "Insufficient data for pattern analysis"}

    # Check if this is a speculative shell
    if "is_speculative" in df.columns and df.iloc[0].get("is_speculative"):
        return {"detected": ["None"], "observation": "Speculative mode: visual analysis required"}

    try:
        last_5 = df.tail(5)
        patterns = []

        curr = last_5.iloc[-1]
        prev = last_5.iloc[-2]

        c_close, c_open = float(curr['Close']), float(curr['Open'])
        p_close, p_open = float(prev['Close']), float(prev['Open'])
        c_high,  c_low  = float(curr['High']),  float(curr['Low'])

        body        = abs(c_close - c_open)
        total_range = c_high - c_low
        upper_wick  = c_high - max(c_open, c_close)
        lower_wick  = min(c_open, c_close) - c_low

        # 1. Engulfing
        if c_close > p_open and c_open < p_close and p_close < p_open:
            patterns.append("Bullish Engulfing")
        elif c_close < p_open and c_open > p_close and p_close > p_open:
            patterns.append("Bearish Engulfing")

        # 2. Pin Bar / Hammer
        if total_range > 0:
            if lower_wick > body * 2 and upper_wick < body:
                patterns.append("Hammer / Bullish Pin Bar")
            elif upper_wick > body * 2 and lower_wick < body:
                patterns.append("Shooting Star / Bearish Pin Bar")

        # 3. Doji — indecision (body < 10% of range)
        if total_range > 0 and body < total_range * 0.1:
            patterns.append("Doji (Indecision)")

        # 4. Inside Bar — consolidation / breakout setup
        p_high, p_low = float(prev['High']), float(prev['Low'])
        if c_high < p_high and c_low > p_low:
            patterns.append("Inside Bar (Consolidation)")

        # 5. Outside Bar / Engulfing Range
        if c_high > p_high and c_low < p_low:
            if c_close > c_open:
                patterns.append("Outside Bar Bullish")
            else:
                patterns.append("Outside Bar Bearish")

        # 6. Three White Soldiers / Three Black Crows (3-candle trend confirmation)
        if len(last_5) >= 3:
            c1, c2, c3 = last_5.iloc[-3], last_5.iloc[-2], last_5.iloc[-1]
            if (float(c1['Close']) > float(c1['Open']) and
                    float(c2['Close']) > float(c2['Open']) and
                    float(c3['Close']) > float(c3['Open']) and
                    float(c2['Close']) > float(c1['Close']) and
                    float(c3['Close']) > float(c2['Close'])):
                patterns.append("Three White Soldiers (Strong Bullish)")
            elif (float(c1['Close']) < float(c1['Open']) and
                    float(c2['Close']) < float(c2['Open']) and
                    float(c3['Close']) < float(c3['Open']) and
                    float(c2['Close']) < float(c1['Close']) and
                    float(c3['Close']) < float(c2['Close'])):
                patterns.append("Three Black Crows (Strong Bearish)")

        # 7. Morning Star / Evening Star (3-candle reversal)
        if len(last_5) >= 3:
            s1, s2, s3 = last_5.iloc[-3], last_5.iloc[-2], last_5.iloc[-1]
            s1_body = abs(float(s1['Close']) - float(s1['Open']))
            s2_body = abs(float(s2['Close']) - float(s2['Open']))
            s3_body = abs(float(s3['Close']) - float(s3['Open']))
            # Morning Star: large bearish, small body (gap down), large bullish
            if (float(s1['Close']) < float(s1['Open']) and
                    s2_body < s1_body * 0.3 and
                    float(s3['Close']) > float(s3['Open']) and
                    s3_body > s1_body * 0.5):
                patterns.append("Morning Star (Bullish Reversal)")
            # Evening Star: large bullish, small body, large bearish
            elif (float(s1['Close']) > float(s1['Open']) and
                    s2_body < s1_body * 0.3 and
                    float(s3['Close']) < float(s3['Open']) and
                    s3_body > s1_body * 0.5):
                patterns.append("Evening Star (Bearish Reversal)")

        return {
            "detected": patterns if patterns else ["None"],
            "observation": f"Latest candle body: {round(body, 2)}, range: {round(total_range, 2)}, upper_wick: {round(upper_wick, 2)}, lower_wick: {round(lower_wick, 2)}"
        }
    except Exception as e:
        logger.error(f"Error in detect_patterns: {e}")
        return {"detected": ["None"], "error": str(e)}

def analyze_trend_channels(df: pd.DataFrame) -> dict:
    """
    Trend Agent (Inspired by QuantAgent).
    Calculates trend slope and support/resistance levels.
    """
    if df is None or len(df) < 20:
        return {"status": "Insufficient data for trend analysis"}

    # Check if this is a speculative shell
    if "is_speculative" in df.columns and df.iloc[0].get("is_speculative"):
        return {"status": "Speculative mode: Trend analysis unavailable"}

    try:
        import math

        # Drop NaN values first
        clean_df = df.dropna(subset=['Close', 'High', 'Low'])
        if len(clean_df) < 2:
            return {"status": "Not enough valid data"}

        closes = clean_df['Close'].values
        x = np.arange(len(closes))
        slope, intercept = np.polyfit(x, closes, 1)

        trend = "UP" if slope > 0 else "DOWN"
        mean_close = closes.mean()
        strength = abs(slope) / mean_close * 100 if mean_close != 0 else 0

        # Support/Resistance based on rolling Min/Max
        support = clean_df['Low'].tail(20).min()
        resistance = clean_df['High'].tail(20).max()

        def safe_float(v):
            if v is None or math.isnan(v) or math.isinf(v):
                return 0.0
            return round(float(v), 4)

        return {
            "primary_trend": trend,
            "slope_strength": safe_float(strength),
            "levels": {
                "support": safe_float(support),
                "resistance": safe_float(resistance)
            },
            "market_phase": "Trending" if safe_float(strength) > 0.05 else "Consolidating"
        }
    except Exception as e:
        logger.error(f"Error in analyze_trend_channels: {e}")
        return {"status": "Error", "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SMART MONEY / ICT ANALYSIS ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def detect_session(dt=None) -> str:
    """Return current trading session: ASIA / LONDON / NEW_YORK / OFF."""
    from datetime import datetime, timezone
    now = dt or datetime.now(timezone.utc)
    h = now.hour
    if 22 <= h or h < 7:
        return "ASIA"
    elif 7 <= h < 12:
        return "LONDON"
    elif 12 <= h < 21:
        return "NEW_YORK"
    return "OFF"


def detect_market_regime(df: pd.DataFrame) -> str:
    """
    Detect TREND / RANGE / CHAOS using ADX + Bollinger Band width.
    TREND  : ADX > 22 and clear EMA slope
    RANGE  : ADX < 18, price oscillating inside BB
    CHAOS  : extreme ATR spike (volatility > 3× recent avg)
    """
    if df is None or len(df) < 20:
        return "UNKNOWN"
    try:
        adx   = df["adx_14"].iloc[-1]  if "adx_14"  in df.columns else 0
        atr   = df["atr_14"].dropna()  if "atr_14"  in df.columns else pd.Series([0])
        bb_up = df["bb_upper"].iloc[-1] if "bb_upper" in df.columns else 0
        bb_lo = df["bb_lower"].iloc[-1] if "bb_lower" in df.columns else 0
        close = df["Close"].iloc[-1]

        atr_now = atr.iloc[-1] if not atr.empty else 0
        atr_avg = atr.tail(20).mean() if not atr.empty else 1
        (bb_up - bb_lo) / close if close else 0

        if atr_avg > 0 and atr_now > atr_avg * 3:
            return "CHAOS"
        if adx > 22:
            return "TREND"
        return "RANGE"
    except Exception as e:
        logger.warning(f"detect_market_regime error: {e}")
        return "UNKNOWN"


def detect_market_structure(df: pd.DataFrame, lookback: int = 40) -> dict:
    """
    Detect swing structure: HH/HL (uptrend), LH/LL (downtrend).
    Also detects BOS (Break of Structure) and CHOCH (Change of Character).

    Returns:
      structure   : "BULLISH" | "BEARISH" | "NEUTRAL"
      last_bos    : "BULLISH_BOS" | "BEARISH_BOS" | None
      choch       : bool — potential reversal signal
      swing_high  : last significant swing high price
      swing_low   : last significant swing low price
    """
    result = {"structure": "NEUTRAL", "last_bos": None, "choch": False,
              "swing_high": None, "swing_low": None}
    if df is None or len(df) < 10:
        return result
    try:
        df_s = df.tail(lookback).copy().reset_index(drop=True)
        highs = df_s["High"].values
        lows  = df_s["Low"].values
        n = len(highs)

        # Find swing highs/lows (simple: local max/min with window=3)
        swing_highs, swing_lows = [], []
        for i in range(2, n - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
               highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                swing_highs.append((i, highs[i]))
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
               lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                swing_lows.append((i, lows[i]))

        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            last_sh = swing_highs[-1][1]
            prev_sh = swing_highs[-2][1]
            last_sl = swing_lows[-1][1]
            prev_sl = swing_lows[-2][1]

            result["swing_high"] = round(float(last_sh), 4)
            result["swing_low"]  = round(float(last_sl), 4)

            hh = last_sh > prev_sh
            hl = last_sl > prev_sl
            lh = last_sh < prev_sh
            ll = last_sl < prev_sl

            if hh and hl:
                result["structure"] = "BULLISH"
            elif lh and ll:
                result["structure"] = "BEARISH"
            else:
                result["structure"] = "NEUTRAL"

            # BOS: current close breaks last swing high/low
            cur_close = df_s["Close"].iloc[-1]
            if cur_close > last_sh:
                result["last_bos"] = "BULLISH_BOS"
            elif cur_close < last_sl:
                result["last_bos"] = "BEARISH_BOS"

            # CHOCH: structure was bearish but now BOS bullish (or vice versa)
            if result["structure"] == "BEARISH" and result["last_bos"] == "BULLISH_BOS":
                result["choch"] = True
            elif result["structure"] == "BULLISH" and result["last_bos"] == "BEARISH_BOS":
                result["choch"] = True

    except Exception as e:
        logger.warning(f"detect_market_structure error: {e}")
    return result


def detect_order_blocks(df: pd.DataFrame, lookback: int = 30) -> list:
    """
    Detect Order Blocks (OB) — institutional accumulation/distribution zones.

    Bullish OB: last bearish (red) candle BEFORE a strong bullish impulse (3+ green candles up)
    Bearish OB: last bullish (green) candle BEFORE a strong bearish impulse (3+ red candles down)

    Returns list of last 3 OBs: [{"type", "top", "bottom", "index", "strength"}]
    """
    obs = []
    if df is None or len(df) < 10:
        return obs
    try:
        df_s = df.tail(lookback).copy().reset_index(drop=True)
        closes = df_s["Close"].values
        opens  = df_s["Open"].values
        highs  = df_s["High"].values
        lows   = df_s["Low"].values
        n = len(closes)

        for i in range(1, n - 3):
            is_bearish = closes[i] < opens[i]
            is_bullish = closes[i] > opens[i]

            # Check for bullish impulse after candle i (at least 2 bullish candles)
            impulse_up   = sum(1 for j in range(i+1, min(i+4, n)) if closes[j] > opens[j])
            impulse_down = sum(1 for j in range(i+1, min(i+4, n)) if closes[j] < opens[j])

            if is_bearish and impulse_up >= 2:
                strength = round(abs(closes[i+1] - opens[i+1]) / (highs[i] - lows[i] + 1e-9), 2)
                obs.append({"type": "BULLISH_OB", "top": round(float(highs[i]), 4),
                             "bottom": round(float(lows[i]), 4), "strength": strength})
            elif is_bullish and impulse_down >= 2:
                strength = round(abs(opens[i+1] - closes[i+1]) / (highs[i] - lows[i] + 1e-9), 2)
                obs.append({"type": "BEARISH_OB", "top": round(float(highs[i]), 4),
                             "bottom": round(float(lows[i]), 4), "strength": strength})

        # Return strongest 3
        obs_sorted = sorted(obs, key=lambda x: x["strength"], reverse=True)
        return obs_sorted[:3]
    except Exception as e:
        logger.warning(f"detect_order_blocks error: {e}")
        return []


def detect_fvg(df: pd.DataFrame, lookback: int = 30) -> list:
    """
    Detect Fair Value Gaps (FVG) / Imbalance zones.

    Bullish FVG: candle[i].low > candle[i-2].high  (gap up — price left imbalance)
    Bearish FVG: candle[i].high < candle[i-2].low  (gap down — price left imbalance)

    Returns up to 3 most recent unfilled FVGs.
    """
    fvgs = []
    if df is None or len(df) < 5:
        return fvgs
    try:
        df_s = df.tail(lookback).copy().reset_index(drop=True)
        highs = df_s["High"].values
        lows  = df_s["Low"].values
        n = len(highs)

        for i in range(2, n):
            gap_size_bull = lows[i] - highs[i-2]
            gap_size_bear = lows[i-2] - highs[i]

            if gap_size_bull > 0:  # Bullish FVG
                fvgs.append({"type": "BULLISH_FVG",
                              "top":    round(float(lows[i]), 4),
                              "bottom": round(float(highs[i-2]), 4),
                              "gap_size": round(float(gap_size_bull), 4),
                              "candle_index": i})
            elif gap_size_bear > 0:  # Bearish FVG
                fvgs.append({"type": "BEARISH_FVG",
                              "top":    round(float(lows[i-2]), 4),
                              "bottom": round(float(highs[i]), 4),
                              "gap_size": round(float(gap_size_bear), 4),
                              "candle_index": i})

        # Most recent 3
        return fvgs[-3:] if len(fvgs) >= 3 else fvgs
    except Exception as e:
        logger.warning(f"detect_fvg error: {e}")
        return []


def detect_liquidity_pools(df: pd.DataFrame, lookback: int = 50, tolerance_pct: float = 0.002) -> dict:
    """
    Detect liquidity pools: equal highs (buy-side liq) and equal lows (sell-side liq).
    Two highs/lows are "equal" if within tolerance_pct of each other.

    Returns:
      buy_side  : list of price levels with clustered highs (targets for bearish sweep)
      sell_side : list of price levels with clustered lows  (targets for bullish sweep)
    """
    result = {"buy_side": [], "sell_side": [], "nearest_sweep_target": None}
    if df is None or len(df) < 10:
        return result
    try:
        df_s = df.tail(lookback)
        cur  = float(df_s["Close"].iloc[-1])

        # Cluster highs
        hs = df_s["High"].values
        for i in range(len(hs)):
            cluster = [hs[j] for j in range(len(hs))
                       if abs(hs[j] - hs[i]) / (hs[i] + 1e-9) < tolerance_pct]
            if len(cluster) >= 2:
                lvl = round(float(np.mean(cluster)), 4)
                if lvl not in result["buy_side"]:
                    result["buy_side"].append(lvl)

        # Cluster lows
        ls = df_s["Low"].values
        for i in range(len(ls)):
            cluster = [ls[j] for j in range(len(ls))
                       if abs(ls[j] - ls[i]) / (ls[i] + 1e-9) < tolerance_pct]
            if len(cluster) >= 2:
                lvl = round(float(np.mean(cluster)), 4)
                if lvl not in result["sell_side"]:
                    result["sell_side"].append(lvl)

        # Deduplicate and sort
        result["buy_side"]  = sorted(set(result["buy_side"]),  reverse=True)[:3]
        result["sell_side"] = sorted(set(result["sell_side"]))[:3]

        # Nearest sweep target — where will SM likely go next?
        above = [p for p in result["buy_side"]  if p > cur]
        below = [p for p in result["sell_side"] if p < cur]
        if above and below:
            nearest_above = min(above)
            nearest_below = max(below)
            result["nearest_sweep_target"] = (
                nearest_above if (nearest_above - cur) < (cur - nearest_below)
                else nearest_below
            )

        return result
    except Exception as e:
        logger.warning(f"detect_liquidity_pools error: {e}")
        return result

def detect_liquidity_sweeps(df: pd.DataFrame, lookback: int = 40) -> dict:
    """
    Detect Liquidity Sweeps: price pierces a significant swing high/low but fails to close beyond it.
    This is often a sign of institutional stop-hunting before a reversal.
    """
    result = {"sweep_detected": False, "type": None, "level": None}
    if df is None or len(df) < lookback:
        return result
    try:
        df_s = df.tail(lookback).copy().reset_index(drop=True)
        highs = df_s["High"].values
        lows  = df_s["Low"].values
        closes = df_s["Close"].values

        # Current candle data
        cur_high  = highs[-1]
        cur_low   = lows[-1]
        cur_close = closes[-1]

        # Find previous significant swing points (excluding latest candles)
        # We look for the peak in the range [0, n-3]
        prev_range = df_s.iloc[:-2]
        p_high = prev_range["High"].max()
        p_low  = prev_range["Low"].min()

        # Bullish Sweep: Price went below p_low but closed back above it
        if cur_low < p_low and cur_close > p_low:
            result = {"sweep_detected": True, "type": "BULLISH_SWEEP", "level": round(float(p_low), 4)}

        # Bearish Sweep: Price went above p_high but closed back below it
        elif cur_high > p_high and cur_close < p_high:
            result = {"sweep_detected": True, "type": "BEARISH_SWEEP", "level": round(float(p_high), 4)}

        return result
    except Exception as e:
        logger.warning(f"detect_liquidity_sweeps error: {e}")
        return result



def get_smart_money_analysis(df: pd.DataFrame) -> dict:
    """
    Full Smart Money / ICT analysis bundle.
    Returns regime, structure, OBs, FVGs, liquidity, and session.
    """
    if df is None or df.empty:
        return {}
    try:
        regime    = detect_market_regime(df)
        structure = detect_market_structure(df)
        obs       = detect_order_blocks(df)
        fvgs      = detect_fvg(df)
        liquidity = detect_liquidity_pools(df)
        sweeps    = detect_liquidity_sweeps(df)
        session   = detect_session()

        # Nearest relevant OB to current price
        cur = float(df["Close"].iloc[-1])
        nearest_ob = None
        if obs:
            obs_with_dist = [(ob, min(abs(ob["top"] - cur), abs(ob["bottom"] - cur))) for ob in obs]
            obs_with_dist.sort(key=lambda x: x[1])
            nearest_ob = obs_with_dist[0][0]

        # Nearest FVG
        nearest_fvg = None
        if fvgs:
            fvgs_with_dist = [(fvg, min(abs(fvg["top"] - cur), abs(fvg["bottom"] - cur))) for fvg in fvgs]
            fvgs_with_dist.sort(key=lambda x: x[1])
            nearest_fvg = fvgs_with_dist[0][0]

        return {
            "session":       session,
            "regime":        regime,
            "structure":     structure,
            "order_blocks":  obs,
            "nearest_ob":    nearest_ob,
            "fvg":           fvgs,
            "nearest_fvg":   nearest_fvg,
            "liquidity":     liquidity,
            "sweeps":        sweeps,
        }
    except Exception as e:
        logger.warning(f"get_smart_money_analysis error: {e}")
        return {}
