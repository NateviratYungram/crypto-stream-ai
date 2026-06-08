"""
CryptoStream AI - Airflow DAG: Market Data Anomaly Detection
============================================================
DAG ID   : market_data_anomaly_detection
Schedule : Every 30 minutes

Purpose:
  Detect adaptive statistical anomalies in market_ohlcv data and persist them
  into data_anomaly_events for operator review, BI reporting, and AI context.

Checks:
  - price_return_spike: close-to-close return exceeds rolling z-score threshold
  - volume_spike: volume exceeds rolling z-score and median-ratio threshold
  - candle_range_spike: high-low range expands far above rolling median
  - missing_candle_gap: candle timestamp gap exceeds expected timeframe spacing
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict

from airflow.datasets import Dataset
from airflow.operators.python import PythonOperator

from airflow import DAG
from intelligence.ml.anomaly_detection import detect_market_anomalies
from intelligence.ml.anomaly_store import (
    connect,
    fetch_recent_ohlcv,
    notify_critical_anomalies,
    persist_anomaly_events_with_details,
)

DS_MARKET_OHLCV = Dataset("postgres://postgres:5432/crypto_stream_db/market_ohlcv")
DS_ANOMALY_EVENTS = Dataset("postgres://postgres:5432/crypto_stream_db/data_anomaly_events")

log = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "data-engineering-team",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
}


def run_anomaly_detection(**context):
    conn = connect()
    try:
        rows = fetch_recent_ohlcv(conn)
        if not rows:
            log.info("[Anomaly] No market_ohlcv rows found in recent lookback window")
            return {"rows_scanned": 0, "events_detected": 0, "events_inserted": 0}

        events = detect_market_anomalies(rows)
        inserted, inserted_events = persist_anomaly_events_with_details(conn, events)
        notified = notify_critical_anomalies(inserted_events)
        severity_counts: Dict[str, int] = {}
        for event in events:
            severity_counts[event["severity"]] = severity_counts.get(event["severity"], 0) + 1

        log.info(
            "[Anomaly] rows=%s detected=%s inserted=%s severity_counts=%s",
            len(rows),
            len(events),
            inserted,
            severity_counts,
        )
        return {
            "rows_scanned": len(rows),
            "events_detected": len(events),
            "events_inserted": inserted,
            "critical_notification_sent": notified,
            "severity_counts": severity_counts,
        }
    finally:
        conn.close()


with DAG(
    dag_id="market_data_anomaly_detection",
    description="Adaptive anomaly detection for market_ohlcv price, volume, and timestamp gaps",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule_interval="*/30 * * * *",
    catchup=False,
    max_active_runs=1,
    tags=["data-quality", "anomaly-detection", "ai-readiness"],
) as dag:
    t_detect = PythonOperator(
        task_id="detect_market_data_anomalies",
        python_callable=run_anomaly_detection,
        provide_context=True,
        inlets=[DS_MARKET_OHLCV],
        outlets=[DS_ANOMALY_EVENTS],
    )
