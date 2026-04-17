# -*- coding: utf-8 -*-
"""
ML Retrain DAG

Schedule: daily at 01:00 UTC (after US market close + data settled)

Tasks:
  1. scan_outcomes   — close any paper trades that hit SL/TP overnight
  2. build_dataset   — pull latest OHLCV + backtest → labeled rows
  3. train_model     — fit GradientBoostingClassifier, save to data/signal_model.pkl
  4. log_metrics     — push accuracy + AUC to XCom for monitoring
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator


DEFAULT_ARGS = {
    "owner":            "cryptostream",
    "depends_on_past":  False,
    "start_date":       datetime(2025, 1, 1),
    "retries":          1,
    "retry_delay":      timedelta(minutes=10),
    "email_on_failure": False,
}

dag = DAG(
    dag_id="ml_retrain",
    default_args=DEFAULT_ARGS,
    schedule_interval="0 1 * * *",   # daily 01:00 UTC
    catchup=False,
    max_active_runs=1,
    tags=["ml", "learning"],
    description="Daily retrain of the signal win-probability model",
)


# ── Task 1: Scan & close paper trades ────────────────────────────────────────
def _scan_outcomes(**ctx):
    from intelligence.ml.outcome_tracker import scan_and_update
    summary = scan_and_update()
    print(f"Outcome scan: {summary}")
    ctx["ti"].xcom_push(key="outcome_summary", value=summary)


# ── Task 2: Build ML dataset from backtests ──────────────────────────────────
def _build_dataset(**ctx):
    from intelligence.ml.signal_model import build_ml_dataset
    df = build_ml_dataset(limit=2000)
    n  = len(df) if df is not None and not df.empty else 0
    print(f"Dataset built: {n} rows")
    ctx["ti"].xcom_push(key="n_rows", value=n)


# ── Task 3: Train model ───────────────────────────────────────────────────────
def _train_model(**ctx):
    from intelligence.ml.signal_model import train_model, invalidate_model_cache
    result = train_model(limit=2000)
    print(f"Training result: {result}")
    invalidate_model_cache()
    ctx["ti"].xcom_push(key="train_result", value=result)


# ── Task 4: Log metrics ───────────────────────────────────────────────────────
def _log_metrics(**ctx):
    ti     = ctx["ti"]
    result = ti.xcom_pull(task_ids="train_model", key="train_result") or {}
    if "error" in result:
        raise RuntimeError(f"Training failed: {result['error']}")
    print(
        f"[ML Metrics] "
        f"n={result.get('n_samples')} | "
        f"accuracy={result.get('accuracy')} | "
        f"AUC={result.get('roc_auc')} | "
        f"win_rate={result.get('win_rate')}"
    )


# ── Wire tasks ────────────────────────────────────────────────────────────────
t_scan  = PythonOperator(task_id="scan_outcomes",  python_callable=_scan_outcomes,  dag=dag, provide_context=True)
t_data  = PythonOperator(task_id="build_dataset",  python_callable=_build_dataset,  dag=dag, provide_context=True)
t_train = PythonOperator(task_id="train_model",    python_callable=_train_model,    dag=dag, provide_context=True)
t_log   = PythonOperator(task_id="log_metrics",    python_callable=_log_metrics,    dag=dag, provide_context=True)

t_scan >> t_data >> t_train >> t_log
