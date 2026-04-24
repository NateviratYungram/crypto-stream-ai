"""
CryptoStream AI — Airflow DAG: FRED Macro Indicators Ingestion
===============================================================
DAG ID   : fred_ingestion
Schedule : Daily at 21:00 UTC (FRED publishes new data ~16:00 ET)

Purpose:
  Pull key macro-economic series from the Federal Reserve Economic Data (FRED)
  API and store them in macro_indicators table. This gives the AI agent and
  dbt mart_cross_asset model the context to answer questions like:
    "How does BTC perform when the yield curve inverts?"
    "Is there a pattern between CPI releases and crypto sell-offs?"

FRED series collected:
  DFF      — Federal Funds Effective Rate (daily)
  T10Y2Y   — 10Y-2Y Treasury Spread / Yield Curve (daily, recession indicator)
  CPIAUCSL — Consumer Price Index, All Urban Consumers (monthly)
  UNRATE   — Unemployment Rate (monthly)
  M2SL     — M2 Money Supply (monthly, liquidity proxy)

Why FRED (not a paid data provider):
  - Free, no API key required for public series
  - Official US government data — highest credibility
  - Used by every major bank and hedge fund globally
  - Demonstrates multi-source ingestion beyond single exchange feed

Table created on first run (CREATE TABLE IF NOT EXISTS — idempotent).
Upsert on (series_id, date) — safe to re-run without duplication.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import List

import psycopg2
import psycopg2.extras
import requests

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

FRED_BASE_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# FRED series to ingest: (series_id, human-readable name, frequency)
FRED_SERIES = [
    ("DFF",       "Federal Funds Effective Rate",          "daily"),
    ("T10Y2Y",    "10Y-2Y Treasury Yield Spread",          "daily"),
    ("CPIAUCSL",  "Consumer Price Index (All Urban)",      "monthly"),
    ("UNRATE",    "Unemployment Rate",                     "monthly"),
    ("M2SL",      "M2 Money Supply",                       "monthly"),
]

DEFAULT_ARGS = {
    "owner":            "data-engineering-team",
    "depends_on_past":  False,
    "email_on_failure": False,
    "retries":          3,
    "retry_delay":      timedelta(minutes=10),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_conn():
    return psycopg2.connect(**DB_CONFIG)


def _ensure_table(conn):
    """Create macro_indicators table if it does not exist yet."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS macro_indicators (
                series_id    VARCHAR(20)   NOT NULL,
                series_name  VARCHAR(100)  NOT NULL,
                date         DATE          NOT NULL,
                value        DECIMAL(20,6),
                frequency    VARCHAR(10)   NOT NULL,
                fetched_at   TIMESTAMPTZ   DEFAULT NOW(),
                PRIMARY KEY (series_id, date)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_macro_indicators_date
                ON macro_indicators (date DESC, series_id)
        """)
    conn.commit()


def _fetch_series(series_id: str, lookback_days: int = 365) -> List[dict]:
    """
    Download a FRED series as CSV and return list of {date, value} dicts.
    FRED public CSV endpoint requires no API key.
    """
    observation_start = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    url = f"{FRED_BASE_URL}?id={series_id}&vintage_date=9999-12-31"
    params = {"id": series_id, "observation_start": observation_start}

    resp = requests.get(FRED_BASE_URL, params=params, timeout=30)
    resp.raise_for_status()

    rows = []
    for line in resp.text.strip().splitlines()[1:]:  # skip header
        parts = line.split(",")
        if len(parts) != 2:
            continue
        date_str, val_str = parts
        val_str = val_str.strip()
        if val_str == "." or not val_str:  # FRED uses "." for missing values
            continue
        try:
            rows.append({"date": date_str.strip(), "value": float(val_str)})
        except ValueError:
            continue

    return rows


def _upsert_rows(conn, series_id: str, series_name: str, frequency: str, rows: List[dict]) -> int:
    if not rows:
        return 0
    tuples = [
        (series_id, series_name, r["date"], r["value"], frequency)
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO macro_indicators (series_id, series_name, date, value, frequency)
            VALUES %s
            ON CONFLICT (series_id, date) DO UPDATE
                SET value      = EXCLUDED.value,
                    fetched_at = NOW()
            """,
            tuples,
            page_size=500,
        )
    conn.commit()
    return len(tuples)


# ---------------------------------------------------------------------------
# Task functions
# ---------------------------------------------------------------------------

def ingest_fred_series(**context):
    """Fetch all configured FRED series and upsert into macro_indicators."""
    conn = _get_conn()
    _ensure_table(conn)

    total_rows = 0
    errors = []

    for series_id, series_name, frequency in FRED_SERIES:
        try:
            rows = _fetch_series(series_id, lookback_days=400)
            n = _upsert_rows(conn, series_id, series_name, frequency, rows)
            total_rows += n
            log.info("FRED %-12s — upserted %d rows", series_id, n)
        except Exception as exc:
            log.error("FRED %s failed: %s", series_id, exc)
            errors.append(f"{series_id}: {exc}")

    conn.close()

    if errors:
        raise RuntimeError(f"FRED ingestion partial failure:\n" + "\n".join(errors))

    log.info("FRED ingestion complete — total rows upserted: %d", total_rows)
    context["ti"].xcom_push(key="total_rows", value=total_rows)


def validate_fred_data(**context):
    """
    Basic freshness check: assert that DFF (daily series) has data for yesterday.
    Warns if data is stale — FRED sometimes delays publication by 1-2 business days.
    """
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT MAX(date) AS latest_date, COUNT(*) AS total_rows
            FROM macro_indicators
            WHERE series_id = 'DFF'
        """)
        row = cur.fetchone()
    conn.close()

    latest_date, total_rows = row
    log.info("FRED DFF latest date: %s | total rows: %d", latest_date, total_rows)

    expected_latest = (datetime.utcnow() - timedelta(days=3)).date()
    if latest_date and latest_date < expected_latest:
        log.warning(
            "FRED DFF data may be stale — latest: %s, expected >= %s",
            latest_date, expected_latest,
        )


# ---------------------------------------------------------------------------
# DAG
# ---------------------------------------------------------------------------
with DAG(
    dag_id="fred_ingestion",
    description="Daily FRED macro indicators ingestion (Fed Rate, CPI, Yield Curve, Unemployment, M2)",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule_interval="0 21 * * *",
    catchup=False,
    max_active_runs=1,
    tags=["macro", "fred", "market-data", "daily"],
) as dag:

    t_ingest = PythonOperator(
        task_id="ingest_fred_series",
        python_callable=ingest_fred_series,
        provide_context=True,
    )

    t_validate = PythonOperator(
        task_id="validate_freshness",
        python_callable=validate_fred_data,
        provide_context=True,
    )

    t_ingest >> t_validate
