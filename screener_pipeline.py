import os
import sys
import time
import json
import sqlite3
import logging
import asyncio
import warnings
import pandas as pd
import yfinance as yf
import httpx
from datetime import datetime
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from functools import partial

# Silence scikit-learn configuration propagation warnings in multi-processing
# These are common when using sklearn models inside ProcessPoolExecutor
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn.utils.parallel")

# Add project root to path
sys.path.append(str(Path.cwd()))

from intelligence.constants import NASDAQ_100_TICKERS, SP500_TICKERS, SMALL_CAP_TICKERS
from intelligence.ml.signal_model import predict_win_probability
from intelligence.ml.feature_extractor import extract_features
from intelligence.technical_engine import compute_indicators

# Force UTF-8 for Windows CMD to support emojis
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] ScreenerPipeline — %(message)s',
    handlers=[
        logging.FileHandler("screener_pipeline.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ScreenerPipeline")

DB_PATH = "screener_v3.db"
SYNC_SLEEP_SECONDS = 60

TIMEFRAME_CONFIGS = {
    "1h": {"yf_interval": "1h", "yf_period": "60d", "crypto_interval": "1h", "crypto_limit": 500},
    "4h": {"yf_interval": "1h", "yf_period": "60d", "resample": "4h", "crypto_interval": "4h", "crypto_limit": 500},
    "1d": {"yf_interval": "1d", "yf_period": "1y", "crypto_interval": "1d", "crypto_limit": 365},
    "1w": {"yf_interval": "1wk", "yf_period": "5y", "crypto_interval": "1w", "crypto_limit": 260},
    "1mo": {"yf_interval": "1mo", "yf_period": "10y", "crypto_interval": "1M", "crypto_limit": 120},
    "1y": {"yf_interval": "1mo", "yf_period": "10y", "resample": "YE", "crypto_interval": "1M", "crypto_limit": 120, "crypto_resample": "YE"},
}

DEFAULT_TIMEFRAME = "1d"

TIMEFRAME_SYNC_EVERY_CYCLES = {
    "1h": 1,
    "4h": 1,
    "1d": 3,
    "1w": 15,
    "1mo": 30,
    "1y": 60,
}

# Blacklist of delisted or problematic tickers to skip (reduces timeouts)
TICKER_BLACKLIST = {
    "MULN", "ASTR", "NKLA", "GRPH", "HYZN", "FSR", "GOEV", "SOLO", 
    "DUNE", "PSTH", "AJAX", "RLAY", "GNPX", "BRPM", "COVA", "FTIV",
    "ZAZZT", "ZBZZT", "ZCZZT", "ZXYZ.A", "KERN", "NVRO", "PROS", "IMGO", "MTTR",
    "RDFN", "SWAV", "MKFG", "APHA", "AXNX", "NCBJ", "SWN", "LAZR", "EVTOL", "PRTY",
    "VTLE", "ARCHER", "RVNC", "CURO", "AJRD", "GNOG", "SAGE", "CCHWF", "SPRT", "LILM",
    "HOL", "BGFV", "GOGL", "YMAB", "EZCORP", "VR",
    "ZEV", "VERV", "EXPR", "AKRO", "WISH", "VERB", "VORB", "AYRO", "IDEX", "ARVL",
    "BLUE", "TTCF", "RIDE", "SDC", "CDEV", "FFIE", "GAMETK", "DMGI"
}

# Global Concurrency Control
process_executor = None
# Optimized Semaphore: 3 concurrent downloads strike a balance between speed and stability
download_semaphore = asyncio.Semaphore(3)
BATCH_SIZE = 500 # Increased batch size for massive scans to reduce overhead

# Curated list of top crypto assets for the screener (Binance-verified)
CRYPTO_SCREENER_LIST = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "DOT", "LINK", "MATIC",
    "LTC", "BCH", "SHIB", "AVAX", "UNI", "ATOM", "XMR", "ETC", "XLM", "ALGO",
    "NEAR", "FIL", "ICP", "HBAR", "SAND", "MANA", "FTM", "APE", "EGLD", "AXS",
    "THETA", "VET", "GRT", "EOS", "FLOW", "AAVE", "KCS", "MKR", "BTT", "CHZ"
]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    # Enable WAL mode for concurrent read/write support
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS screener_data (
            symbol TEXT PRIMARY KEY,
            universe TEXT,
            price REAL,
            rsi REAL,
            vol_ratio REAL,
            pct_from_52wh REAL,
            return_1w_pct REAL,
            ai_score REAL,
            rationale TEXT,
            updated_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS screener_snapshots (
            symbol TEXT,
            timeframe TEXT,
            universe TEXT,
            price REAL,
            rsi REAL,
            vol_ratio REAL,
            pct_from_period_high REAL,
            return_pct REAL,
            ai_score REAL,
            rationale TEXT,
            updated_at TIMESTAMP,
            PRIMARY KEY (symbol, timeframe)
        )
    """)
    # Add index for faster filtering by universe
    conn.execute("CREATE INDEX IF NOT EXISTS idx_universe ON screener_data(universe)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_timeframe_universe ON screener_snapshots(timeframe, universe)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_timeframe_score ON screener_snapshots(timeframe, ai_score)")
    conn.commit()
    conn.close()

def _normalize_ohlcv(df):
    """Return OHLCV columns with a DatetimeIndex when possible."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if "Datetime" in out.columns:
        out["Datetime"] = pd.to_datetime(out["Datetime"], errors="coerce")
        out = out.dropna(subset=["Datetime"]).set_index("Datetime")
    elif "OpenTime" in out.columns:
        out["Datetime"] = pd.to_datetime(out["OpenTime"], unit="ms", errors="coerce")
        out = out.dropna(subset=["Datetime"]).set_index("Datetime")
    if not isinstance(out.index, pd.DatetimeIndex):
        try:
            out.index = pd.to_datetime(out.index)
        except Exception:
            return out
    return out

def _resample_ohlcv(df, rule):
    if not rule:
        return df
    df = _normalize_ohlcv(df)
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return df
    agg = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }
    available = {k: v for k, v in agg.items() if k in df.columns}
    return df.resample(rule).agg(available).dropna(subset=["Open", "High", "Low", "Close"])

def _calculate_snapshot(sym, df, universe, timeframe, now_ts, asset_class):
    if df is None or df.empty:
        return None

    sym_df = compute_indicators(df)
    closes = sym_df["Close"].dropna().tolist()
    volumes = sym_df["Volume"].dropna().tolist()
    highs = sym_df["High"].dropna().tolist()

    if len(closes) < 20:
        return None

    price = closes[-1]
    rsi = sym_df["rsi_14"].iloc[-1]
    lookback = min(6, len(closes) - 1)
    return_pct = ((closes[-1] / closes[-1 - lookback]) - 1) * 100 if lookback > 0 else 0.0

    avg_vol = sum(volumes[-21:-1]) / max(len(volumes[-21:-1]), 1) if len(volumes) > 1 else 1
    vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

    period_high = max(highs)
    pct_from_period_high = ((period_high - price) / period_high) * 100 if period_high > 0 else 0.0

    feats = extract_features(sym_df, len(sym_df)-1, symbol=sym, asset_class=asset_class)
    ai_res = predict_win_probability(feats)
    ai_score = ai_res.get("win_pct", 50.0)
    rationale = ", ".join(ai_res.get("rationale", []))

    return (
        sym, timeframe, universe, round(price, 2), round(rsi, 2),
        round(vol_ratio, 3), round(pct_from_period_high, 2), round(return_pct, 3),
        ai_score, rationale, now_ts
    )

def process_single_symbol(sym, df_json, universe, now_ts, timeframe=DEFAULT_TIMEFRAME):
    """CPU-bound task to process a single symbol."""
    try:
        # Reconstruct DataFrame from JSON if passed as JSON (to avoid pickling issues)
        # But for now we try passing the slice directly as it's usually picklable
        df = pd.read_json(df_json) if isinstance(df_json, str) else df_json
        
        sym_df = (
            df[sym] if (isinstance(df.columns, pd.MultiIndex) and sym in df.columns.get_level_values(0))
            else df if not isinstance(df.columns, pd.MultiIndex)
            else None
        )
        if sym_df is None or sym_df.empty:
            return None
        
        cfg = TIMEFRAME_CONFIGS.get(timeframe, TIMEFRAME_CONFIGS[DEFAULT_TIMEFRAME])
        sym_df = _resample_ohlcv(sym_df, cfg.get("resample"))
        return _calculate_snapshot(sym, sym_df, universe, timeframe, now_ts, "STOCK")
    except Exception:
        return None

async def process_batch(symbols: list, universe: str, semaphore: asyncio.Semaphore, timeframe: str = DEFAULT_TIMEFRAME):
    """Downloads batch data and parallelizes symbol processing."""
    # Filter out blacklisted symbols
    symbols = [s for s in symbols if s not in TICKER_BLACKLIST]
    if not symbols: return []

    async with download_semaphore:
        results = []
        try:
            tickers_str = " ".join(symbols)
            loop = asyncio.get_event_loop()
            cfg = TIMEFRAME_CONFIGS.get(timeframe, TIMEFRAME_CONFIGS[DEFAULT_TIMEFRAME])
            
            # Use threads=False for stability in concurrent asyncio environment
            df = await loop.run_in_executor(None, partial(
                yf.download, tickers_str, period=cfg["yf_period"], interval=cfg["yf_interval"],
                progress=False, group_by="ticker", auto_adjust=True, 
                threads=False, timeout=25
            ))
            
            if df.empty:
                return []
            
            now_ts = datetime.now().isoformat()
            tasks = []
            for sym in symbols:
                tasks.append(loop.run_in_executor(process_executor, process_single_symbol, sym, df, universe, now_ts, timeframe))
            
            processed_results = await asyncio.gather(*tasks)
            results = [r for r in processed_results if r is not None]
            update_db(results, timeframe)
            
        except Exception as e:
            logger.error(f"Batch error for {universe}/{timeframe}: {e}")
    return results

def update_db(data, timeframe: str = DEFAULT_TIMEFRAME):
    if not data:
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executemany("""
            INSERT OR REPLACE INTO screener_snapshots
            (symbol, timeframe, universe, price, rsi, vol_ratio, pct_from_period_high, return_pct, ai_score, rationale, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, data)
        if timeframe == DEFAULT_TIMEFRAME:
            legacy_rows = [
                (sym, universe, price, rsi, vol_ratio, pct_high, ret, ai_score, rationale, updated_at)
                for sym, _timeframe, universe, price, rsi, vol_ratio, pct_high, ret, ai_score, rationale, updated_at in data
            ]
            conn.executemany("""
                INSERT OR REPLACE INTO screener_data 
                (symbol, universe, price, rsi, vol_ratio, pct_from_52wh, return_1w_pct, ai_score, rationale, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, legacy_rows)
        conn.commit()
    finally:
        conn.close()

def update_legacy_db(data):
    if not data:
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executemany("""
            INSERT OR REPLACE INTO screener_data 
            (symbol, universe, price, rsi, vol_ratio, pct_from_52wh, return_1w_pct, ai_score, rationale, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, data)
        conn.commit()
    finally:
        conn.close()

async def sync_crypto_symbol(client, sym, now_ts):
    """Asynchronously sync a single crypto symbol."""
    try:
        url = "https://api.binance.com/api/v3/klines"
        r = await client.get(url, params={"symbol": sym + "USDT", "interval": "1d", "limit": 200}, timeout=10)
        if r.status_code == 200:
            raw = r.json()
            cols = ["OpenTime", "Open", "High", "Low", "Close", "Volume", "CloseTime", "QuoteAssetVol", "Trades", "TakerBuyBase", "TakerBuyQuote", "Ignore"]
            pdf = pd.DataFrame(raw, columns=cols)
            for c in ["Open", "High", "Low", "Close", "Volume"]:
                pdf[c] = pdf[c].astype(float)
            
            loop = asyncio.get_event_loop()
            pdf = await loop.run_in_executor(process_executor, compute_indicators, pdf)
            
            closes = pdf["Close"].tolist()
            volumes = pdf["Volume"].tolist()
            highs = pdf["High"].tolist()
            
            price = closes[-1]
            rsi = pdf["rsi_14"].iloc[-1]
            ret_1w = ((closes[-1] / closes[-6]) - 1) * 100
            avg_vol = sum(volumes[-15:-1]) / max(len(volumes[-15:-1]), 1)
            vol_ratio = volumes[-1] / avg_vol
            period_high = max(highs)
            pct_52wh = ((period_high - price) / period_high) * 100
            
            feats = await loop.run_in_executor(process_executor, extract_features, pdf, len(pdf)-1, sym, "CRYPTO")
            ai_res = predict_win_probability(feats)
            ai_score = ai_res.get("win_pct", 50.0)
            rationale = ", ".join(ai_res.get("rationale", []))

            return (
                sym, "CRYPTO", round(price, 2), round(rsi, 2),
                round(vol_ratio, 3), round(pct_52wh, 2), round(ret_1w, 3), 
                ai_score, rationale, now_ts
            )
    except Exception as e:
        logger.debug(f"Crypto error {sym}: {e}")
    return None

async def sync_crypto_symbol_timeframe(client, sym, timeframe, now_ts):
    """Asynchronously sync a single crypto symbol/timeframe snapshot."""
    try:
        cfg = TIMEFRAME_CONFIGS.get(timeframe, TIMEFRAME_CONFIGS[DEFAULT_TIMEFRAME])
        url = "https://api.binance.com/api/v3/klines"
        r = await client.get(
            url,
            params={"symbol": sym + "USDT", "interval": cfg["crypto_interval"], "limit": cfg["crypto_limit"]},
            timeout=10,
        )
        if r.status_code != 200:
            return None

        raw = r.json()
        cols = ["OpenTime", "Open", "High", "Low", "Close", "Volume", "CloseTime", "QuoteAssetVol", "Trades", "TakerBuyBase", "TakerBuyQuote", "Ignore"]
        pdf = pd.DataFrame(raw, columns=cols)
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            pdf[c] = pdf[c].astype(float)
        pdf = _resample_ohlcv(pdf, cfg.get("crypto_resample"))

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            process_executor,
            _calculate_snapshot,
            sym,
            pdf,
            "CRYPTO",
            timeframe,
            now_ts,
            "CRYPTO",
        )
    except Exception as e:
        logger.debug(f"Crypto error {sym}/{timeframe}: {e}")
    return None

async def sync_universe(universe: str, symbols: list, timeframe: str = DEFAULT_TIMEFRAME):
    """Processes an entire universe in controlled batches using global concurrency control."""
    logger.info(f"🔄 Syncing {universe} ({len(symbols)} assets)...")
    
    batch_tasks = []
    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i:i+BATCH_SIZE]
        batch_tasks.append(process_batch(batch, universe, download_semaphore, timeframe))
    
    await asyncio.gather(*batch_tasks)
    logger.info(f"✅ Sync {universe} complete.")

async def run_pipeline_async():
    """Main high-performance loop that syncs everything in one sequence."""
    logger.info("🚀 Starting Full Market Pipeline (Comprehensive Mode)...")
    init_db()
    
    # Load tickers
    try:
        base_dir = Path(__file__).parent
        json_path = base_dir / "intelligence" / "market_data" / "index_tickers.json"
        with open(json_path, "r") as f:
            index_data = json.load(f)
            full_sp500 = index_data.get("indices", {}).get("SP500", [])
            full_nasdaq = index_data.get("exchanges", {}).get("NASDAQ", [])
    except Exception as e:
        full_sp500 = SP500_TICKERS
        full_nasdaq = NASDAQ_100_TICKERS

    tasks_config = [
        ("NASDAQ100", NASDAQ_100_TICKERS),
        ("SP500", full_sp500),
        ("NASDAQ", full_nasdaq),
        ("SMALL_CAP", SMALL_CAP_TICKERS)
    ]
    cycle_count = 0

    while True:
        try:
            cycle_count += 1
            cycle_start = time.time()
            logger.info("--- Starting New Full Sync Cycle ---")
            active_timeframes = [
                tf for tf, every in TIMEFRAME_SYNC_EVERY_CYCLES.items()
                if cycle_count == 1 or cycle_count % every == 0
            ]
            
            # 1. Sync Priority Core Assets First
            priority_tickers = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NFLX", "AMD", "AVGO", "COST", "COIN", "MSTR"]
            for timeframe in active_timeframes:
                await process_batch(priority_tickers, "PRIORITY", download_semaphore, timeframe)

            # 2. Sync Crypto (Parallel with Stocks)
            async def crypto_flow(timeframe):
                now_ts = datetime.now().isoformat()
                async with httpx.AsyncClient() as client:
                    crypto_tasks = [sync_crypto_symbol_timeframe(client, sym, timeframe, now_ts) for sym in CRYPTO_SCREENER_LIST]
                    crypto_results = await asyncio.gather(*crypto_tasks)
                    update_db([r for r in crypto_results if r is not None], timeframe)
            
            for timeframe in active_timeframes:
                await crypto_flow(timeframe)

            # 3. Full Market Sweep (Universes)
            for timeframe in active_timeframes:
                for u, s in tasks_config:
                    await sync_universe(u, s, timeframe)

            duration = time.time() - cycle_start
            logger.info(f"✅ Full Cycle Complete. Total Duration: {duration:.2f}s")
            logger.info(f"Sleeping for {SYNC_SLEEP_SECONDS}s...")
            await asyncio.sleep(SYNC_SLEEP_SECONDS)

        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    # Efficiency fix: Limit workers to half the CPU cores to leave room for the OS/Browser
    num_workers = max(2, (os.cpu_count() or 4) // 2)
    process_executor = ProcessPoolExecutor(max_workers=num_workers)
    try:
        asyncio.run(run_pipeline_async())
    except KeyboardInterrupt:
        logger.info("Pipeline stopped by user.")
    finally:
        process_executor.shutdown()
