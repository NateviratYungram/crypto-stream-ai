"""
CryptoStream AI — Airflow DAG: Data Retention & Cleanup
========================================================
DAG ID   : data_retention
Schedule : 03:00 AM UTC daily (after daily_aggregation and BigQuery DAGs)

Purpose:
  Enforce retention policies on fast-growing tables to prevent unbounded
  PostgreSQL growth and query degradation.

Retention rules:
  market_ohlcv
    - 15m candles : keep 90 days  (intraday analysis window)
    - 1h  candles : keep 365 days (medium-term trend analysis)
    - 1d  candles : keep forever  (historical backtesting — small row count)

  enriched_trades  : keep 30 days  (Flink raw trades — high volume)
  market_metrics   : keep 90 days  (1-min VWAP aggregates)
  data_quality_log : keep 180 days (regulatory audit requirement)
  mcp_audit_log    : keep 365 days (security audit requirement)

  Dead tables (candles_m5 / m15 / h1 / h4):
    - Dropped and removed — nothing writes to them, they waste space.
    - market_ohlcv replaces them as the unified OHLCV store.

Gap detection:
  After pruning, scan market_ohlcv for gaps in macro symbols (15m timeframe).
  Log any gap > 2× the expected interval so operators can investigate.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
from airflow.operators.python import PythonOperator

from airflow import DAG

log = logging.getLogger(__name__)

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
    "retries":          1,
    "retry_delay":      timedelta(minutes=5),
}

# Retention windows (days)
RETENTION = {
    "market_ohlcv_15m":    90,
    "market_ohlcv_1h":    365,
    "enriched_trades":     30,
    "market_metrics":      90,
    "data_quality_log":   180,
    "mcp_audit_log":      365,
}

# Macro tickers to check for gaps (embedded — no intelligence/ import needed)
MACRO_TICKERS = [
    "GC=F", "SI=F", "CL=F", "HG=F", "NG=F",
    "^IXIC", "^GSPC", "^DJI",
    "BTC-USD", "ETH-USD", "SOL-USD",
]


def _get_conn():
    return psycopg2.connect(**DB_CONFIG)


# ---------------------------------------------------------------------------
# Task 1: Prune market_ohlcv by timeframe
# ---------------------------------------------------------------------------
def prune_market_ohlcv(**_):
    conn = _get_conn()
    total_deleted = 0

    with conn.cursor() as cur:
        # 15m: keep 90 days
        cutoff_15m = datetime.utcnow() - timedelta(days=RETENTION["market_ohlcv_15m"])
        cur.execute(
            "DELETE FROM market_ohlcv WHERE timeframe = '15m' AND ts < %s",
            (cutoff_15m,),
        )
        deleted = cur.rowcount
        total_deleted += deleted
        log.info(f"Pruned market_ohlcv 15m: {deleted:,} rows (cutoff {cutoff_15m.date()})")

        # 1h: keep 365 days
        cutoff_1h = datetime.utcnow() - timedelta(days=RETENTION["market_ohlcv_1h"])
        cur.execute(
            "DELETE FROM market_ohlcv WHERE timeframe = '1h' AND ts < %s",
            (cutoff_1h,),
        )
        deleted = cur.rowcount
        total_deleted += deleted
        log.info(f"Pruned market_ohlcv 1h:  {deleted:,} rows (cutoff {cutoff_1h.date()})")

        # 1d: keep forever — skip
        log.info("market_ohlcv 1d: retained forever (small row count)")

    conn.commit()
    conn.close()
    log.info(f"market_ohlcv total pruned: {total_deleted:,} rows")


# ---------------------------------------------------------------------------
# Task 2: Prune high-volume operational tables
# ---------------------------------------------------------------------------
def prune_operational_tables(**_):
    conn = _get_conn()
    with conn.cursor() as cur:
        # enriched_trades (raw tick data — highest volume)
        cutoff = datetime.utcnow() - timedelta(days=RETENTION["enriched_trades"])
        cur.execute(
            "DELETE FROM enriched_trades WHERE ingestion_time < %s",
            (cutoff,),
        )
        log.info(f"Pruned enriched_trades: {cur.rowcount:,} rows (cutoff {cutoff.date()})")

        # market_metrics (1-min VWAP)
        cutoff = datetime.utcnow() - timedelta(days=RETENTION["market_metrics"])
        cur.execute(
            "DELETE FROM market_metrics WHERE window_start < %s",
            (cutoff,),
        )
        log.info(f"Pruned market_metrics:  {cur.rowcount:,} rows (cutoff {cutoff.date()})")

        # data_quality_log (regulatory: 180 days)
        cutoff = datetime.utcnow() - timedelta(days=RETENTION["data_quality_log"])
        cur.execute(
            "DELETE FROM data_quality_log WHERE detected_at < %s",
            (cutoff,),
        )
        log.info(f"Pruned data_quality_log: {cur.rowcount:,} rows (cutoff {cutoff.date()})")

        # mcp_audit_log (security: 365 days)
        cutoff = datetime.utcnow() - timedelta(days=RETENTION["mcp_audit_log"])
        cur.execute(
            "DELETE FROM mcp_audit_log WHERE created_at < %s",
            (cutoff,),
        )
        log.info(f"Pruned mcp_audit_log:   {cur.rowcount:,} rows (cutoff {cutoff.date()})")

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Task 3: Drop dead candle tables (nothing writes to them)
# ---------------------------------------------------------------------------
def drop_dead_candle_tables(**_):
    """
    candles_m5 / m15 / h1 / h4 were created in schema.sql but nothing writes
    to them. market_ohlcv is the unified replacement. Drop to reclaim space.
    Uses IF EXISTS so this is safe to re-run.
    """
    conn = _get_conn()
    with conn.cursor() as cur:
        for table in ("candles_m5", "candles_m15", "candles_h1", "candles_h4"):
            cur.execute(f"DROP TABLE IF EXISTS {table}")
            log.info(f"Dropped dead table: {table}")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Task 4: Gap detection on macro symbols (15m timeframe)
# ---------------------------------------------------------------------------
def detect_ohlcv_gaps(**context):
    """
    Scan the last 48h of market_ohlcv for gaps > 30 min in macro symbols.
    Logs warnings for ops team; pushes gap count to XCom for alerting.
    """
    conn = _get_conn()
    since = datetime.utcnow() - timedelta(hours=48)
    gap_count = 0

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for ticker in MACRO_TICKERS:
            cur.execute("""
                SELECT
                    ts,
                    LAG(ts) OVER (ORDER BY ts) AS prev_ts,
                    EXTRACT(EPOCH FROM (ts - LAG(ts) OVER (ORDER BY ts))) AS gap_secs
                FROM market_ohlcv
                WHERE symbol = %s AND timeframe = '15m' AND ts >= %s
                ORDER BY ts
            """, (ticker, since))

            rows = cur.fetchall()
            for row in rows:
                if row["gap_secs"] and row["gap_secs"] > 1800:
                    log.warning(
                        f"GAP DETECTED | {ticker} | 15m | "
                        f"{row['prev_ts']} → {row['ts']} | "
                        f"{row['gap_secs'] / 60:.0f} min gap"
                    )
                    gap_count += 1

    conn.close()

    if gap_count == 0:
        log.info("Gap detection: no gaps found in macro 15m data (last 48h)")
    else:
        log.warning(f"Gap detection: {gap_count} gaps found — check yfinance-ingester logs")

    context["ti"].xcom_push(key="gap_count", value=gap_count)
    return gap_count


# ---------------------------------------------------------------------------
# Task 5: VACUUM ANALYZE after mass deletes (reclaim storage)
# ---------------------------------------------------------------------------
def vacuum_analyze(**_):
    """
    Run VACUUM ANALYZE after bulk deletes so PostgreSQL reclaims disk space
    and updates table statistics for the query planner.
    Must run in autocommit mode (cannot run inside a transaction block).
    """
    conn = _get_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        for table in ("market_ohlcv", "enriched_trades", "market_metrics",
                      "data_quality_log", "mcp_audit_log", "news_sentiment"):
            try:
                cur.execute(f"VACUUM ANALYZE {table}")
                log.info(f"VACUUM ANALYZE completed: {table}")
            except Exception as e:
                log.warning(f"VACUUM ANALYZE skipped for {table}: {e}")
    conn.close()


# ---------------------------------------------------------------------------
# DAG Definition
# ---------------------------------------------------------------------------
with DAG(
    dag_id="data_retention",
    description="Enforce retention policies and detect data gaps in market_ohlcv",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule_interval="0 3 * * *",   # 03:00 UTC daily
    catchup=False,
    tags=["data-quality", "retention", "ops"],
) as dag:

    t_prune_ohlcv = PythonOperator(
        task_id="prune_market_ohlcv",
        python_callable=prune_market_ohlcv,
        provide_context=True,
    )

    t_prune_ops = PythonOperator(
        task_id="prune_operational_tables",
        python_callable=prune_operational_tables,
        provide_context=True,
    )

    t_drop_dead = PythonOperator(
        task_id="drop_dead_candle_tables",
        python_callable=drop_dead_candle_tables,
        provide_context=True,
    )

    t_gaps = PythonOperator(
        task_id="detect_ohlcv_gaps",
        python_callable=detect_ohlcv_gaps,
        provide_context=True,
    )

    t_vacuum = PythonOperator(
        task_id="vacuum_analyze",
        python_callable=vacuum_analyze,
        provide_context=True,
    )

    # Prune all tables in parallel, then gap-check, then vacuum
    [t_prune_ohlcv, t_prune_ops, t_drop_dead] >> t_gaps >> t_vacuum
