"""
CryptoStream AI — Airflow DAG: Hourly Feature Store Computation
================================================================
DAG ID   : feature_store
Schedule : Top of every hour (0 * * * *)

Purpose:
  Read OHLCV from market_ohlcv, compute statistical features for every
  tracked symbol, and upsert into market_features + market_regime tables.

  Enables the AI agent to answer cross-asset questions instantly:
    "BTC decoupled จาก SP500 มั้ย?"        → corr_vs_sp500_30d
    "หุ้นไหน outperform ตลาดช่วงนี้?"      → rel_strength_30d ranking
    "ตอนนี้ตลาดอยู่ใน risk-on มั้ย?"       → market_regime.regime
    "NVDA ผันผวนกว่าตลาดเท่าไหร่?"         → beta_vs_sp500

Features computed per symbol:
  - Returns:       1d / 7d / 30d / 90d / 365d
  - Volatility:    7d / 30d / 90d (annualized)
  - Correlation:   vs SP500, vs BTC, vs Gold (30d & 90d windows)
  - Beta:          vs SP500 (90d OLS)
  - Price context: % from 52-week high/low
  - Rel. strength: vs SP500 (30d)

Global regime per day (market_regime):
  - SP500 + crypto realized volatility
  - BTC/SP500 30d correlation
  - RISK_ON / RISK_OFF / NEUTRAL classification
  - SP500 and BTC position vs 200-day MA
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

from airflow import DAG
from airflow.operators.python import PythonOperator

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

DEFAULT_ARGS = {
    "owner":            "data-engineering-team",
    "depends_on_past":  False,
    "email_on_failure": False,
    "retries":          2,
    "retry_delay":      timedelta(minutes=5),
}

# Benchmarks used for correlation / beta calculations
BENCHMARK_SP500 = "^GSPC"
BENCHMARK_BTC   = "BTC-USD"
BENCHMARK_GOLD  = "GC=F"
TIMEFRAME       = "1d"

# Minimum rows required to compute a feature (avoid division by zero / noise)
MIN_ROWS_30D  = 15
MIN_ROWS_90D  = 45
MIN_ROWS_365D = 200


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _conn():
    return psycopg2.connect(**DB_CONFIG)


def _load_prices(conn, symbols: List[str], lookback_days: int = 400) -> pd.DataFrame:
    """
    Load daily close prices from market_ohlcv for given symbols.
    Returns a wide DataFrame: index=date, columns=symbol.
    """
    since = date.today() - timedelta(days=lookback_days)
    sql = """
        SELECT symbol, ts::date AS dt, close
        FROM   market_ohlcv
        WHERE  timeframe = '1d'
          AND  ts::date  >= %s
          AND  symbol    = ANY(%s)
        ORDER  BY dt ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (since, symbols))
        rows = cur.fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["symbol", "dt", "close"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    wide = df.pivot_table(index="dt", columns="symbol", values="close", aggfunc="last")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


def _get_all_symbols(conn) -> List[str]:
    """Return distinct symbols that have at least 30 days of 1d data."""
    sql = """
        SELECT symbol
        FROM   market_ohlcv
        WHERE  timeframe = '1d'
        GROUP  BY symbol
        HAVING COUNT(*) >= 30
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Feature computation helpers
# ---------------------------------------------------------------------------
def _safe(val):
    """Return None if val is NaN/Inf, else round to 6 dp."""
    if val is None:
        return None
    try:
        v = float(val)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    except Exception:
        return None


def _return(series: pd.Series, n: int) -> Optional[float]:
    """n-day price return."""
    if len(series) < n + 1:
        return None
    ret = (series.iloc[-1] - series.iloc[-n - 1]) / series.iloc[-n - 1]
    return _safe(ret)


def _volatility(series: pd.Series, n: int) -> Optional[float]:
    """Annualized realized volatility over n days."""
    if len(series) < n + 2:
        return None
    log_ret = np.log(series.iloc[-n:] / series.iloc[-n:].shift(1)).dropna()
    if len(log_ret) < n // 2:
        return None
    return _safe(log_ret.std() * math.sqrt(252))


def _correlation(s1: pd.Series, s2: pd.Series, n: int) -> Optional[float]:
    """Pearson correlation of daily returns over last n days."""
    combined = pd.concat([s1, s2], axis=1).dropna()
    if len(combined) < max(MIN_ROWS_30D, n // 2):
        return None
    combined = combined.iloc[-n:]
    ret1 = combined.iloc[:, 0].pct_change().dropna()
    ret2 = combined.iloc[:, 1].pct_change().dropna()
    aligned = pd.concat([ret1, ret2], axis=1).dropna()
    if len(aligned) < MIN_ROWS_30D:
        return None
    return _safe(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))


def _beta(asset: pd.Series, benchmark: pd.Series, n: int = 90) -> Optional[float]:
    """OLS beta of asset returns vs benchmark returns over n days."""
    combined = pd.concat([asset, benchmark], axis=1).dropna().iloc[-n:]
    if len(combined) < MIN_ROWS_90D:
        return None
    r_asset = combined.iloc[:, 0].pct_change().dropna()
    r_bench = combined.iloc[:, 1].pct_change().dropna()
    aligned = pd.concat([r_asset, r_bench], axis=1).dropna()
    if len(aligned) < MIN_ROWS_90D:
        return None
    cov = aligned.cov().iloc[0, 1]
    var = aligned.iloc[:, 1].var()
    return _safe(cov / var) if var else None


def _pct_from_high_low(series: pd.Series) -> Tuple[Optional[float], Optional[float]]:
    """% distance from 52-week high and low."""
    if len(series) < 2:
        return None, None
    window = series.iloc[-252:] if len(series) >= 252 else series
    curr = series.iloc[-1]
    high = window.max()
    low  = window.min()
    pct_high = _safe((curr - high) / high * 100) if high else None
    pct_low  = _safe((curr - low)  / low  * 100) if low  else None
    return pct_high, pct_low


# ---------------------------------------------------------------------------
# Task 1: Compute per-symbol features and upsert market_features
# ---------------------------------------------------------------------------
def compute_symbol_features(**_):
    conn = _conn()
    today = date.today()

    symbols = _get_all_symbols(conn)
    if not symbols:
        log.warning("No symbols found in market_ohlcv — skipping feature computation")
        conn.close()
        return

    # Ensure benchmarks are in the load list even if missing from tracked symbols
    load_symbols = list(set(symbols + [BENCHMARK_SP500, BENCHMARK_BTC, BENCHMARK_GOLD]))
    log.info(f"Computing features for {len(symbols)} symbols (loading {len(load_symbols)} price series)")

    prices = _load_prices(conn, load_symbols, lookback_days=400)
    if prices.empty:
        log.error("price DataFrame is empty — no data in market_ohlcv?")
        conn.close()
        return

    sp500 = prices.get(BENCHMARK_SP500, pd.Series(dtype=float))
    btc   = prices.get(BENCHMARK_BTC,   pd.Series(dtype=float))
    gold  = prices.get(BENCHMARK_GOLD,  pd.Series(dtype=float))

    rows = []
    for sym in symbols:
        if sym not in prices.columns:
            continue
        s = prices[sym].dropna()
        if len(s) < 5:
            continue

        pct_high, pct_low = _pct_from_high_low(s)

        # Relative strength vs SP500 (30d return difference)
        r30_asset = _return(s, 30)
        r30_sp500 = _return(sp500, 30) if len(sp500) >= 31 else None
        rel_str_30d = _safe(r30_asset - r30_sp500) if (r30_asset and r30_sp500) else None

        rows.append({
            "symbol":            sym,
            "date":              today,
            "return_1d":         _return(s, 1),
            "return_7d":         _return(s, 7),
            "return_30d":        r30_asset,
            "return_90d":        _return(s, 90),
            "return_365d":       _return(s, 365),
            "volatility_7d":     _volatility(s, 7),
            "volatility_30d":    _volatility(s, 30),
            "volatility_90d":    _volatility(s, 90),
            "corr_vs_sp500_30d": _correlation(s, sp500, 30),
            "corr_vs_sp500_90d": _correlation(s, sp500, 90),
            "corr_vs_btc_30d":   _correlation(s, btc,   30),
            "corr_vs_btc_90d":   _correlation(s, btc,   90),
            "corr_vs_gold_30d":  _correlation(s, gold,  30),
            "beta_vs_sp500":     _beta(s, sp500, 90),
            "pct_from_52w_high": pct_high,
            "pct_from_52w_low":  pct_low,
            "rel_strength_30d":  rel_str_30d,
        })

    if not rows:
        log.warning("No feature rows computed")
        conn.close()
        return

    insert_sql = """
        INSERT INTO market_features (
            symbol, date,
            return_1d, return_7d, return_30d, return_90d, return_365d,
            volatility_7d, volatility_30d, volatility_90d,
            corr_vs_sp500_30d, corr_vs_sp500_90d,
            corr_vs_btc_30d, corr_vs_btc_90d, corr_vs_gold_30d,
            beta_vs_sp500, pct_from_52w_high, pct_from_52w_low,
            rel_strength_30d
        ) VALUES %s
        ON CONFLICT (symbol, date) DO UPDATE SET
            return_1d          = EXCLUDED.return_1d,
            return_7d          = EXCLUDED.return_7d,
            return_30d         = EXCLUDED.return_30d,
            return_90d         = EXCLUDED.return_90d,
            return_365d        = EXCLUDED.return_365d,
            volatility_7d      = EXCLUDED.volatility_7d,
            volatility_30d     = EXCLUDED.volatility_30d,
            volatility_90d     = EXCLUDED.volatility_90d,
            corr_vs_sp500_30d  = EXCLUDED.corr_vs_sp500_30d,
            corr_vs_sp500_90d  = EXCLUDED.corr_vs_sp500_90d,
            corr_vs_btc_30d    = EXCLUDED.corr_vs_btc_30d,
            corr_vs_btc_90d    = EXCLUDED.corr_vs_btc_90d,
            corr_vs_gold_30d   = EXCLUDED.corr_vs_gold_30d,
            beta_vs_sp500      = EXCLUDED.beta_vs_sp500,
            pct_from_52w_high  = EXCLUDED.pct_from_52w_high,
            pct_from_52w_low   = EXCLUDED.pct_from_52w_low,
            rel_strength_30d   = EXCLUDED.rel_strength_30d,
            computed_at        = NOW()
    """
    tuples = [
        (r["symbol"], r["date"],
         r["return_1d"], r["return_7d"], r["return_30d"], r["return_90d"], r["return_365d"],
         r["volatility_7d"], r["volatility_30d"], r["volatility_90d"],
         r["corr_vs_sp500_30d"], r["corr_vs_sp500_90d"],
         r["corr_vs_btc_30d"], r["corr_vs_btc_90d"], r["corr_vs_gold_30d"],
         r["beta_vs_sp500"], r["pct_from_52w_high"], r["pct_from_52w_low"],
         r["rel_strength_30d"])
        for r in rows
    ]

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, insert_sql, tuples, page_size=200)
    conn.commit()
    conn.close()
    log.info(f"market_features: upserted {len(rows)} rows for {today}")


# ---------------------------------------------------------------------------
# Task 2: Compute global market regime and upsert market_regime
# ---------------------------------------------------------------------------
def compute_market_regime(**_):
    conn = _conn()
    today = date.today()

    prices = _load_prices(conn, [BENCHMARK_SP500, BENCHMARK_BTC, BENCHMARK_GOLD],
                          lookback_days=250)
    if prices.empty:
        log.warning("No benchmark data — skipping regime computation")
        conn.close()
        return

    sp500 = prices.get(BENCHMARK_SP500, pd.Series(dtype=float)).dropna()
    btc   = prices.get(BENCHMARK_BTC,   pd.Series(dtype=float)).dropna()

    sp500_vol_30d     = _volatility(sp500, 30)
    crypto_vol_30d    = _volatility(btc, 30)
    btc_sp500_corr_30 = _correlation(btc, sp500, 30)

    # SP500 vs 200-day MA
    def _vs_ma200(s: pd.Series) -> Optional[float]:
        if len(s) < 200:
            return None
        ma200 = s.iloc[-200:].mean()
        return _safe((s.iloc[-1] - ma200) / ma200 * 100) if ma200 else None

    sp500_vs_ma200 = _vs_ma200(sp500)
    btc_vs_ma200   = _vs_ma200(btc)

    # ── Regime classification ────────────────────────────────────────────────
    # RISK_ON  : low vol + SP500 above MA200 + BTC correlated with stocks
    # RISK_OFF : high vol OR SP500 below MA200
    # NEUTRAL  : everything else
    drivers = []
    risk_score = 0  # positive = risk-on, negative = risk-off

    if sp500_vol_30d is not None:
        if sp500_vol_30d > 0.25:
            risk_score -= 30
            drivers.append("high_market_volatility")
        elif sp500_vol_30d < 0.12:
            risk_score += 20
            drivers.append("low_market_volatility")

    if crypto_vol_30d is not None:
        if crypto_vol_30d > 0.70:
            risk_score -= 15
            drivers.append("high_crypto_volatility")

    if sp500_vs_ma200 is not None:
        if sp500_vs_ma200 > 0:
            risk_score += 25
            drivers.append("sp500_above_ma200")
        else:
            risk_score -= 25
            drivers.append("sp500_below_ma200")

    if btc_vs_ma200 is not None:
        if btc_vs_ma200 > 0:
            risk_score += 10
            drivers.append("btc_above_ma200")
        else:
            risk_score -= 10
            drivers.append("btc_below_ma200")

    if btc_sp500_corr_30 is not None:
        if btc_sp500_corr_30 > 0.6:
            drivers.append("btc_sp500_correlated")   # crypto moving with stocks
        elif btc_sp500_corr_30 < 0.1:
            drivers.append("btc_sp500_decoupled")    # crypto diverging

    if risk_score >= 30:
        regime, confidence = "RISK_ON",  min(100, 50 + risk_score)
    elif risk_score <= -20:
        regime, confidence = "RISK_OFF", min(100, 50 + abs(risk_score))
    else:
        regime, confidence = "NEUTRAL",  50.0

    insert_sql = """
        INSERT INTO market_regime (
            date, sp500_vol_30d, crypto_vol_30d, btc_sp500_corr_30d,
            regime, regime_confidence, regime_drivers,
            sp500_vs_ma200, btc_vs_ma200
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (date) DO UPDATE SET
            sp500_vol_30d      = EXCLUDED.sp500_vol_30d,
            crypto_vol_30d     = EXCLUDED.crypto_vol_30d,
            btc_sp500_corr_30d = EXCLUDED.btc_sp500_corr_30d,
            regime             = EXCLUDED.regime,
            regime_confidence  = EXCLUDED.regime_confidence,
            regime_drivers     = EXCLUDED.regime_drivers,
            sp500_vs_ma200     = EXCLUDED.sp500_vs_ma200,
            btc_vs_ma200       = EXCLUDED.btc_vs_ma200,
            computed_at        = NOW()
    """
    with conn.cursor() as cur:
        cur.execute(insert_sql, (
            today,
            sp500_vol_30d, crypto_vol_30d, btc_sp500_corr_30,
            regime, round(confidence, 2), json.dumps(drivers),
            sp500_vs_ma200, btc_vs_ma200,
        ))
    conn.commit()
    conn.close()
    log.info(f"market_regime: {today} → {regime} ({confidence:.0f}%) | drivers={drivers}")


# ---------------------------------------------------------------------------
# DAG Definition
# ---------------------------------------------------------------------------
with DAG(
    dag_id="feature_store",
    description="Hourly precompute of returns, volatility, correlation, beta, regime",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule_interval="0 * * * *",    # top of every hour
    catchup=False,
    max_active_runs=1,
    tags=["feature-store", "ai", "analytics"],
) as dag:

    t_symbols = PythonOperator(
        task_id="compute_symbol_features",
        python_callable=compute_symbol_features,
        provide_context=True,
    )

    t_regime = PythonOperator(
        task_id="compute_market_regime",
        python_callable=compute_market_regime,
        provide_context=True,
    )

    # Both tasks are independent — run in parallel
    [t_symbols, t_regime]
