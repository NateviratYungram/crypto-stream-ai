# -*- coding: utf-8 -*-
"""
Outcome Scan DAG

Runs every hour — checks all OPEN paper trades and closes any that hit SL/TP.
Keeps ML labels fresh without waiting for the daily retrain DAG.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow.operators.python import PythonOperator

from airflow import DAG

DEFAULT_ARGS = {
    "owner":            "cryptostream",
    "depends_on_past":  False,
    "start_date":       datetime(2025, 1, 1),
    "retries":          1,
    "retry_delay":      timedelta(minutes=5),
    "email_on_failure": False,
}

dag = DAG(
    dag_id="outcome_scan",
    default_args=DEFAULT_ARGS,
    schedule_interval="0 * * * *",  # every hour
    catchup=False,
    max_active_runs=1,
    tags=["ml", "paper_trades"],
    description="Hourly scan: close paper trades that hit SL/TP, refresh adaptive thresholds",
)


def _scan_and_close(**ctx):
    from intelligence.ml.outcome_tracker import scan_and_update
    summary = scan_and_update()
    print(
        f"[OutcomeScan] scanned={summary['scanned']} "
        f"closed_win={summary['closed_win']} "
        f"closed_loss={summary['closed_loss']} "
        f"errors={summary['errors']}"
    )
    ctx["ti"].xcom_push(key="outcome_summary", value=summary)


def _update_thresholds(**ctx):
    from intelligence.ml.symbol_threshold import update_thresholds
    from intelligence.ml.trading_quality_gate import clear_trading_quality_gate_cache
    thresholds = update_thresholds()
    clear_trading_quality_gate_cache()
    print(f"[OutcomeScan] adaptive thresholds updated: {thresholds}")
    ctx["ti"].xcom_push(key="thresholds", value=thresholds)


t_scan = PythonOperator(
    task_id="scan_and_close",
    python_callable=_scan_and_close,
    dag=dag,
    provide_context=True,
)

t_thresholds = PythonOperator(
    task_id="update_adaptive_thresholds",
    python_callable=_update_thresholds,
    dag=dag,
    provide_context=True,
)

t_scan >> t_thresholds
