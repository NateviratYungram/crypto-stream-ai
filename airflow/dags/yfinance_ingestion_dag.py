"""
CryptoStream AI — Airflow DAG: yfinance Market Data Ingestion
=============================================================
DAG ID   : yfinance_ingestion
Schedule :
  - Macro symbols  (11)  → every 15 minutes (*/15 * * * *)
  - Stock symbols  (600) → daily at 22:30 UTC (after US market close)

Purpose:
  Ensures market_ohlcv table always has fresh OHLCV data so the AI agent
  can answer from the DB instead of making live yfinance API calls.

Task flow (macro run):
    fetch_macro_15m → upsert_macro_15m
    fetch_macro_1h  → upsert_macro_1h
    fetch_macro_1d  → upsert_macro_1d

Task flow (stocks run, daily):
    fetch_stocks_1d → upsert_stocks_1d
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List

import psycopg2
import psycopg2.extras
import yfinance as yf
from airflow.datasets import Dataset
from airflow.operators.python import PythonOperator

from airflow import DAG

DS_MARKET_OHLCV = Dataset("postgres://postgres:5432/crypto_stream_db/market_ohlcv")

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_CONFIG = {
    "host":     "postgres",
    "port":     5432,
    "dbname":   "crypto_stream_db",
    "user":     "user",
    "password": "password",
}

YF_BATCH_SIZE  = 20
YF_BATCH_SLEEP = 1.5   # seconds between batches

DEFAULT_ARGS = {
    "owner":            "data-engineering-team",
    "depends_on_past":  False,
    "email_on_failure": False,
    "retries":          2,
    "retry_delay":      timedelta(minutes=3),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_conn():
    return psycopg2.connect(**DB_CONFIG)


def _upsert_rows(conn, rows: list) -> int:
    if not rows:
        return 0
    sql = """
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
        psycopg2.extras.execute_values(cur, sql, tuples, page_size=500)
    conn.commit()
    return len(tuples)


def _df_to_rows(df, ticker: str, interval: str) -> list:
    rows = []
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    if "Adj Close" in df.columns:
        df["Close"] = df["Adj Close"]
    import pandas as pd
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


def _fetch_and_upsert(tickers: List[str], period: str, interval: str) -> int:
    """Download from yfinance and upsert into market_ohlcv. Returns row count."""
    import time
    conn = _get_conn()
    total = 0

    for i in range(0, len(tickers), YF_BATCH_SIZE):
        batch = tickers[i: i + YF_BATCH_SIZE]
        try:
            raw = yf.download(
                batch,
                period=period,
                interval=interval,
                progress=False,
                group_by="ticker",
                auto_adjust=True,
                threads=True,
            )
            if raw is None or raw.empty:
                continue

            rows = []
            if len(batch) == 1:
                rows.extend(_df_to_rows(raw, batch[0], interval))
            else:
                for ticker in batch:
                    try:
                        levels = raw.columns.get_level_values(1)
                        if ticker in levels:
                            df = raw.xs(ticker, axis=1, level=1).dropna(how="all")
                        else:
                            continue
                        rows.extend(_df_to_rows(df, ticker, interval))
                    except Exception as e:
                        log.warning(f"Extract failed for {ticker}: {e}")

            total += _upsert_rows(conn, rows)

        except Exception as e:
            log.error(f"Batch {batch[:3]}… failed: {e}")

        time.sleep(YF_BATCH_SLEEP)

    conn.close()
    log.info(f"_fetch_and_upsert({interval}/{period}): {total:,} rows upserted")
    return total


# ---------------------------------------------------------------------------
# Ticker constants — embedded directly so Airflow containers don't need the
# intelligence/ package on their Python path. Keep in sync with
# intelligence/constants.py when adding new symbols.
# ---------------------------------------------------------------------------
_MACRO_TICKERS: List[str] = [
    "GC=F",   # Gold
    "SI=F",   # Silver
    "CL=F",   # Oil (WTI)
    "HG=F",   # Copper
    "NG=F",   # Natural Gas
    "^IXIC",  # NASDAQ
    "^GSPC",  # S&P 500
    "^DJI",   # Dow Jones
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
]

_NASDAQ_100: List[str] = [
    'NVDA','GOOGL','GOOG','AAPL','MSFT','AMZN','AVGO','META','TSLA','WMT',
    'ASML','COST','NFLX','AMD','LRCX','MU','CSCO','AMAT','INTC','PLTR',
    'LIN','KLAC','TMUS','PEP','TXN','AMGN','GILD','ADI','ISRG','ARM',
    'HON','SHOP','PDD','BKNG','QCOM','APP','PANW','WDC','STX','MRVL',
    'VRTX','SBUX','CEG','CMCSA','INTU','CRWD','MAR','ADBE','MELI','CSX',
    'ORLY','ABNB','REGN','ADP','MDLZ','SNPS','MNST','AEP','CDNS','ROST',
    'CTAS','WBD','PCAR','MPWR','DASH','BKR','FTNT','FAST','FANG','NXPI',
    'XEL','EA','EXC','ADSK','IDXX','MSTR','ODFL','ALNY','PYPL','MCHP',
    'DDOG','TTWO','KDP','ROP','GEHC','CPRT','CHTR','PAYX','WDAY','AXON',
    'CTSH','KHC','DXCM','VRSK','ZS','CSGP','TEAM',
]

_SP500_SAMPLE: List[str] = [
    'MMM','ABT','ABBV','ACN','ADBE','AMD','AFL','A','APD','ABNB','ALB',
    'ARE','ALLE','LNT','ALL','MO','AMZN','AEE','AEP','AXP','AIG','AMT',
    'AWK','AMP','AME','AMGN','APH','ADI','AON','APA','AAPL','AMAT','APP',
    'APTV','ADM','ANET','AJG','T','ATO','ADSK','ADP','AZO','AVB','AXON',
    'BKR','BAC','BAX','BDX','BLK','BX','BK','BA','BKNG','BSX','BMY',
    'AVGO','BR','BG','CAT','CBOE','CBRE','CNC','CF','SCHW','CHTR','CVX',
    'CMG','CB','CI','CTAS','CSCO','C','CLX','CME','KO','CTSH','COIN','CL',
    'CMCSA','COP','ED','CEG','COST','CRH','CRWD','CSX','CVS','DHR','DDOG',
    'DE','DELL','DAL','FANG','DLR','DG','DLTR','D','DPZ','DASH','DOV',
    'DUK','ETN','EBAY','ECL','EW','EA','ELV','EMR','EOG','EQIX','EQR',
    'ESS','EL','EXC','EXPE','XOM','FDS','FICO','FAST','FDX','FIS','FITB',
    'FSLR','FISV','F','FTNT','FCX','GRMN','GE','GEHC','GD','GIS','GM',
    'GILD','GS','HAL','HCA','HPE','HLT','HD','HON','HRL','HST','HPQ',
    'HUM','IBM','IDXX','ITW','INTC','ICE','INTU','ISRG','IQV','IRM',
    'JNJ','JPM','KDP','KEY','KMB','KMI','KKR','KLAC','KHC','KR','LHX',
    'LRCX','LEN','LLY','LIN','LMT','LOW','LULU','MTB','MAR','MLM','MA',
    'MCD','MCK','MDT','MRK','META','MET','MU','MSFT','MRNA','MDLZ','MPWR',
    'MNST','MCO','MS','MSI','NFLX','NEM','NEE','NKE','NTRS','NOC','NVDA',
    'NXPI','ORLY','OXY','ODFL','ON','OKE','ORCL','PCAR','PLTR','PANW',
    'PH','PAYX','PYPL','PEP','PFE','PCG','PM','PSX','PNC','PG','PGR',
    'PLD','PRU','PSA','PHM','QCOM','RTX','REGN','RSG','RMD','ROK','ROP',
    'ROST','SPGI','CRM','SLB','NOW','SHW','SPG','SNA','SO','SWK','SBUX',
    'STT','SYK','SYF','SNPS','SYY','TMUS','TSLA','TGT','TMO','TJX','TTD',
    'TFC','USB','UBER','UNP','UAL','UPS','UNH','VLO','VZ','VRTX','V',
    'VMC','WMT','DIS','WM','WAT','WEC','WFC','WELL','WY','WMB','WDAY',
]

def _load_macro_tickers() -> List[str]:
    return _MACRO_TICKERS


def _load_stock_tickers() -> List[str]:
    return list(set(_NASDAQ_100 + _SP500_SAMPLE))


def task_fetch_macro_15m(**_):
    tickers = _load_macro_tickers()
    _fetch_and_upsert(tickers, period="2d", interval="15m")


def task_fetch_macro_1h(**_):
    tickers = _load_macro_tickers()
    _fetch_and_upsert(tickers, period="7d", interval="1h")


def task_fetch_macro_1d(**_):
    tickers = _load_macro_tickers()
    _fetch_and_upsert(tickers, period="5d", interval="1d")


def task_fetch_stocks_1d(**_):
    tickers = _load_stock_tickers()
    _fetch_and_upsert(tickers, period="5d", interval="1d")


# ---------------------------------------------------------------------------
# DAG 1: Macro — every 15 minutes
# ---------------------------------------------------------------------------
with DAG(
    dag_id="yfinance_macro_ingestion",
    description="Refresh macro OHLCV (Gold/Oil/Indices/Crypto) every 15 min",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule_interval="*/15 * * * *",
    catchup=False,
    max_active_runs=1,
    tags=["market-data", "yfinance", "macro", "real-time"],
) as dag_macro:

    t_15m = PythonOperator(
        task_id="fetch_macro_15m",
        python_callable=task_fetch_macro_15m,
        provide_context=True,
        outlets=[DS_MARKET_OHLCV],
    )
    t_1h = PythonOperator(
        task_id="fetch_macro_1h",
        python_callable=task_fetch_macro_1h,
        provide_context=True,
        outlets=[DS_MARKET_OHLCV],
    )
    t_1d = PythonOperator(
        task_id="fetch_macro_1d",
        python_callable=task_fetch_macro_1d,
        provide_context=True,
        outlets=[DS_MARKET_OHLCV],
    )

    # Run all three timeframes in parallel
    [t_15m, t_1h, t_1d]


# ---------------------------------------------------------------------------
# DAG 2: Stocks — daily after US market close (22:30 UTC = 5:30 PM ET)
# ---------------------------------------------------------------------------
with DAG(
    dag_id="yfinance_stocks_ingestion",
    description="Refresh NASDAQ 100 + S&P 500 daily OHLCV after market close",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule_interval="30 22 * * 1-5",   # 22:30 UTC, Mon–Fri
    catchup=False,
    max_active_runs=1,
    tags=["market-data", "yfinance", "stocks", "daily"],
) as dag_stocks:

    PythonOperator(
        task_id="fetch_stocks_1d",
        python_callable=task_fetch_stocks_1d,
        provide_context=True,
        outlets=[DS_MARKET_OHLCV],
    )
