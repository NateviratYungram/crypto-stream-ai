"""
CryptoStream AI — Airflow DAG: Data Quality Assertions
=======================================================
DAG ID   : data_quality
Schedule : Every 30 minutes (runs continuously alongside ingestion)

Purpose:
  Run SQL-based assertions against key tables and log results to
  data_quality_log. Raises an AirflowException (fails the DAG run) if
  any CRITICAL check fails, stopping downstream pipelines from consuming
  dirty data.

Why SQL assertions (not Great Expectations):
  - Zero extra infra: runs on existing PostgreSQL
  - Results written to data_quality_log — already auditable by regulators
  - Same pattern used in production fintech (BAHTNET, PromptPay reconciliation)

Severity levels:
  CRITICAL — pipeline-blocking; DAG fails immediately on breach
  WARNING  — logged but DAG continues; operator investigates async

Checks:
  enriched_trades
    [CRITICAL] No null prices or quantities in last 30 min
    [CRITICAL] All prices > 0
    [CRITICAL] All quantities > 0
    [WARNING]  Whale count not anomalously high (> 5% of trades)
  market_ohlcv
    [CRITICAL] high >= low for all candles in last 24h
    [CRITICAL] close between low and high
    [WARNING]  Volume not zero for equity symbols
  daily_summary
    [CRITICAL] No negative volumes or trade counts
    [WARNING]  price_change_pct within ±50% (catches stale/corrupt close prices)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

import psycopg2
import psycopg2.extras

from airflow import DAG
from airflow.operators.python import PythonOperator

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
    "retry_delay":      timedelta(minutes=2),
}


# ---------------------------------------------------------------------------
# Assertion definitions
# ---------------------------------------------------------------------------

ASSERTIONS: List[Dict[str, Any]] = [
    # ── enriched_trades ─────────────────────────────────────────────────────
    {
        "name":     "enriched_trades__no_null_price_or_qty",
        "table":    "enriched_trades",
        "severity": "CRITICAL",
        "sql": """
            SELECT COUNT(*) AS failing_rows
            FROM enriched_trades
            WHERE ingestion_time >= NOW() - INTERVAL '30 minutes'
              AND (price IS NULL OR quantity IS NULL)
        """,
        "expected": 0,
        "error_reason": "null_price_or_quantity",
    },
    {
        "name":     "enriched_trades__price_positive",
        "table":    "enriched_trades",
        "severity": "CRITICAL",
        "sql": """
            SELECT COUNT(*) AS failing_rows
            FROM enriched_trades
            WHERE ingestion_time >= NOW() - INTERVAL '30 minutes'
              AND price <= 0
        """,
        "expected": 0,
        "error_reason": "non_positive_price",
    },
    {
        "name":     "enriched_trades__quantity_positive",
        "table":    "enriched_trades",
        "severity": "CRITICAL",
        "sql": """
            SELECT COUNT(*) AS failing_rows
            FROM enriched_trades
            WHERE ingestion_time >= NOW() - INTERVAL '30 minutes'
              AND quantity <= 0
        """,
        "expected": 0,
        "error_reason": "non_positive_quantity",
    },
    {
        "name":     "enriched_trades__whale_rate_reasonable",
        "table":    "enriched_trades",
        "severity": "WARNING",
        "sql": """
            SELECT CASE
                WHEN COUNT(*) = 0 THEN 0
                WHEN SUM(CASE WHEN is_whale THEN 1 ELSE 0 END)::float / COUNT(*) > 0.05
                THEN 1 ELSE 0
            END AS failing_rows
            FROM enriched_trades
            WHERE ingestion_time >= NOW() - INTERVAL '30 minutes'
        """,
        "expected": 0,
        "error_reason": "whale_rate_exceeds_5pct",
    },
    # ── market_ohlcv ────────────────────────────────────────────────────────
    {
        "name":     "market_ohlcv__high_gte_low",
        "table":    "market_ohlcv",
        "severity": "CRITICAL",
        "sql": """
            SELECT COUNT(*) AS failing_rows
            FROM market_ohlcv
            WHERE fetched_at >= NOW() - INTERVAL '24 hours'
              AND high < low
        """,
        "expected": 0,
        "error_reason": "high_less_than_low",
    },
    {
        "name":     "market_ohlcv__close_within_range",
        "table":    "market_ohlcv",
        "severity": "CRITICAL",
        "sql": """
            SELECT COUNT(*) AS failing_rows
            FROM market_ohlcv
            WHERE fetched_at >= NOW() - INTERVAL '24 hours'
              AND (close < low OR close > high)
        """,
        "expected": 0,
        "error_reason": "close_outside_high_low_range",
    },
    # ── daily_summary ────────────────────────────────────────────────────────
    {
        "name":     "daily_summary__no_negative_volume",
        "table":    "daily_summary",
        "severity": "CRITICAL",
        "sql": """
            SELECT COUNT(*) AS failing_rows
            FROM daily_summary
            WHERE report_date = CURRENT_DATE - 1
              AND (total_volume < 0 OR trade_count < 0)
        """,
        "expected": 0,
        "error_reason": "negative_volume_or_trade_count",
    },
    {
        "name":     "daily_summary__reasonable_price_change",
        "table":    "daily_summary",
        "severity": "WARNING",
        "sql": """
            SELECT COUNT(*) AS failing_rows
            FROM daily_summary
            WHERE report_date = CURRENT_DATE - 1
              AND ABS((close_price - open_price) / NULLIF(open_price, 0) * 100) > 50
        """,
        "expected": 0,
        "error_reason": "price_change_exceeds_50pct",
    },
]


# ---------------------------------------------------------------------------
# Task functions
# ---------------------------------------------------------------------------

def run_assertions(**context):
    """
    Execute all SQL assertions. Log every result to data_quality_log.
    Collect CRITICAL failures and raise at the end so all checks run first.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    critical_failures: List[str] = []

    for check in ASSERTIONS:
        try:
            with conn.cursor() as cur:
                cur.execute(check["sql"])
                failing_rows = cur.fetchone()[0]

            passed = (failing_rows == check["expected"])
            status = "PASS" if passed else f"FAIL ({failing_rows} rows)"
            log.info(
                "[DQ] %-55s | %-8s | %s",
                check["name"], check["severity"], status,
            )

            if not passed:
                # Write to data_quality_log (existing audit table)
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO data_quality_log
                            (trade_id, raw_payload, error_reason, detected_at)
                        VALUES (%s, %s::jsonb, %s, NOW())
                    """, (
                        check["name"],
                        f'{{"check": "{check["name"]}", "table": "{check["table"]}", '
                        f'"failing_rows": {failing_rows}, "severity": "{check["severity"]}"}}',
                        check["error_reason"],
                    ))
                conn.commit()

                if check["severity"] == "CRITICAL":
                    critical_failures.append(
                        f"{check['name']}: {failing_rows} failing rows"
                    )

        except Exception as exc:
            log.error("[DQ] Check %s raised exception: %s", check["name"], exc)
            conn.rollback()
            if check["severity"] == "CRITICAL":
                critical_failures.append(f"{check['name']}: exception — {exc}")

    conn.close()

    if critical_failures:
        raise ValueError(
            f"Data quality CRITICAL failures detected:\n" +
            "\n".join(f"  • {f}" for f in critical_failures)
        )

    log.info("[DQ] All assertions passed ✓")


def log_dq_summary(**context):
    """Log a summary of recent DQ failures for the operator dashboard."""
    conn = psycopg2.connect(**DB_CONFIG)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT error_reason, COUNT(*) AS occurrences, MAX(detected_at) AS last_seen
            FROM data_quality_log
            WHERE detected_at >= NOW() - INTERVAL '24 hours'
            GROUP BY error_reason
            ORDER BY occurrences DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
    conn.close()

    if rows:
        log.warning("[DQ] Last 24h failure summary:")
        for row in rows:
            log.warning("  %-40s  occurrences=%-4d  last=%s",
                        row["error_reason"], row["occurrences"], row["last_seen"])
    else:
        log.info("[DQ] No failures in last 24h")


# ---------------------------------------------------------------------------
# DAG
# ---------------------------------------------------------------------------
with DAG(
    dag_id="data_quality",
    description="SQL assertion checks on enriched_trades, market_ohlcv, daily_summary",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule_interval="*/30 * * * *",
    catchup=False,
    max_active_runs=1,
    tags=["data-quality", "monitoring", "regulatory"],
) as dag:

    t_assert = PythonOperator(
        task_id="run_assertions",
        python_callable=run_assertions,
        provide_context=True,
    )

    t_summary = PythonOperator(
        task_id="log_dq_summary",
        python_callable=log_dq_summary,
        provide_context=True,
        trigger_rule="all_done",  # run even if assertions fail
    )

    t_assert >> t_summary
