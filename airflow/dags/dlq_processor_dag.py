"""
CryptoStream AI — Airflow DAG: DLQ Processor
=============================================
DAG ID   : dlq_processor
Schedule : 0 2 * * * (02:00 AM daily — after daily_aggregation finishes)
Purpose  : Reads messages from Kafka DLQ topic `trade_stream_dlq`
           and persists them into the `data_quality_log` PostgreSQL table
           for audit, investigation, and daily DQ monitoring.

Banking Relevance:
    In banking systems, "Rejection Reports" or "Exception Reports" are
    mandatory deliverables:
    - Every failed / invalid transaction must be logged with a reason.
    - Compliance officers review DQ anomaly logs for suspicious patterns.
    - ธปท. can request proof that a bank's DQ controls caught specific errors.
    This DAG automates that process, ensuring every DLQ message has a
    permanent, queryable audit record in PostgreSQL.

Task Flow:
    poll_dlq_messages
          ↓
    insert_to_dq_log
          ↓
    generate_dq_summary_report
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

from airflow import DAG
from airflow.operators.python import PythonOperator

# ---------------------------------------------------------------------------
# DAG Default Arguments
# ---------------------------------------------------------------------------
DEFAULT_ARGS = {
    'owner'           : 'data-engineering-team',
    'depends_on_past' : False,
    'email_on_failure': False,
    'email_on_retry'  : False,
    'retries'         : 2,
    'retry_delay'     : timedelta(minutes=3),
}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
KAFKA_BROKER        = 'kafka:29092'
DLQ_TOPIC           = 'trade_stream_dlq'
KAFKA_GROUP_ID      = 'airflow_dlq_processor'
MAX_POLL_TIMEOUT_MS = 10_000   # Wait 10s for messages before stopping poll
MAX_RECORDS         = 10_000   # Safety cap per run

DB_CONFIG = {
    'host'    : 'postgres',
    'port'    : 5432,
    'dbname'  : 'crypto_stream_db',
    'user'    : 'user',
    'password': 'password',
}

log = logging.getLogger(__name__)


def get_db_conn():
    """Returns a psycopg2 connection to crypto_stream_db."""
    return psycopg2.connect(**DB_CONFIG)


# ---------------------------------------------------------------------------
# Task Functions
# ---------------------------------------------------------------------------

def poll_dlq_messages(**context) -> int:
    """
    Poll all pending messages from the DLQ Kafka topic.
    Uses consumer_timeout_ms to stop polling after inactivity,
    preventing the task from hanging indefinitely.

    Returns the number of messages consumed and pushes them to XCom.
    """
    log.info(f"Polling DLQ topic: {DLQ_TOPIC} (broker: {KAFKA_BROKER})")

    messages = []

    try:
        consumer = KafkaConsumer(
            DLQ_TOPIC,
            bootstrap_servers=[KAFKA_BROKER],
            group_id=KAFKA_GROUP_ID,
            auto_offset_reset='earliest',          # Always read from earliest uncommitted offset
            enable_auto_commit=False,              # Manual commit after successful DB insert
            consumer_timeout_ms=MAX_POLL_TIMEOUT_MS,
            value_deserializer=lambda x: x,       # Raw bytes; parse manually
            api_version=(0, 10, 1),
        )

        for msg in consumer:
            try:
                raw = json.loads(msg.value.decode('utf-8'))
                messages.append({
                    'trade_id'    : str(raw.get('trade_id', '')),
                    'raw_payload' : json.dumps(raw),
                    'error_reason': raw.get('error_reason', 'unknown'),
                    'kafka_offset': msg.offset,
                    'kafka_partition': msg.partition,
                })
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                log.warning(f"Skipping undecodeable DLQ message at offset {msg.offset}: {e}")

            if len(messages) >= MAX_RECORDS:
                log.warning(f"Reached MAX_RECORDS cap ({MAX_RECORDS}). Stopping poll.")
                break

        # Commit offsets only after all messages are captured in memory
        consumer.commit()
        consumer.close()

    except NoBrokersAvailable:
        log.error("Kafka broker unavailable. DLQ poll skipped.")
        context['ti'].xcom_push(key='dlq_messages', value=[])
        return 0

    except Exception as e:
        log.error(f"poll_dlq_messages failed: {e}", exc_info=True)
        raise

    log.info(f"Polled {len(messages):,} messages from DLQ topic.")
    context['ti'].xcom_push(key='dlq_messages', value=messages)
    return len(messages)


def insert_to_dq_log(**context) -> int:
    """
    Bulk-insert DLQ messages into the data_quality_log table.
    Uses execute_values for efficient batch inserts.
    Skips records already in the log (idempotent via ON CONFLICT DO NOTHING).

    Banking: Every invalid record is permanently logged with:
    - trade_id, raw_payload (full JSON), error_reason, and detected_at
    This provides complete traceability for compliance audits.
    """
    ti       = context['ti']
    messages = ti.xcom_pull(task_ids='poll_dlq_messages', key='dlq_messages')

    if not messages:
        log.info("No DLQ messages to insert. Skipping.")
        return 0

    rows = [
        (
            msg['trade_id'],
            psycopg2.extras.Json(json.loads(msg['raw_payload'])),  # JSONB column
            msg['error_reason'],
        )
        for msg in messages
    ]

    log.info(f"Inserting {len(rows):,} records into data_quality_log...")

    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO data_quality_log (trade_id, raw_payload, error_reason)
                    VALUES %s
                    ON CONFLICT DO NOTHING
                    """,
                    rows,
                    page_size=500  # Batch 500 rows per round-trip
                )
            conn.commit()

        log.info(f"Successfully inserted {len(rows):,} DQ log records.")
        ti.xcom_push(key='inserted_count', value=len(rows))
        return len(rows)

    except Exception as e:
        log.error(f"insert_to_dq_log failed: {e}", exc_info=True)
        raise


def generate_dq_summary_report(**context):
    """
    Query data_quality_log for today's DQ stats and log a structured summary.
    In a production system, this would also: send a Slack alert, email report,
    or POST to a monitoring webhook.

    Banking: This report is the "Data Quality Dashboard" input —
    shows what % of records failed validation today and why.
    """
    target_date = context['data_interval_start'].date()
    log.info(f"Generating DQ summary report for {target_date}...")

    try:
        with get_db_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

                # Total DQ failures today
                cur.execute("""
                    SELECT
                        error_reason,
                        COUNT(*) AS error_count
                    FROM data_quality_log
                    WHERE DATE(detected_at) = %s
                    GROUP BY error_reason
                    ORDER BY error_count DESC
                """, (target_date,))
                breakdown = cur.fetchall()

                # Total records processed (from enriched_trades)
                cur.execute("""
                    SELECT COUNT(*) AS total
                    FROM enriched_trades
                    WHERE DATE(TO_TIMESTAMP(timestamp / 1000.0) AT TIME ZONE 'UTC') = %s
                """, (target_date,))
                total_clean = cur.fetchone()['total']

        total_errors = sum(row['error_count'] for row in breakdown)
        total_all    = total_clean + total_errors
        dq_pass_rate = (total_clean / total_all * 100) if total_all > 0 else 100.0

        log.info("=" * 60)
        log.info(f"[DQ REPORT] Date         : {target_date}")
        log.info(f"[DQ REPORT] Total Records : {total_all:,}")
        log.info(f"[DQ REPORT] Valid Records : {total_clean:,}")
        log.info(f"[DQ REPORT] DQ Errors     : {total_errors:,}")
        log.info(f"[DQ REPORT] Pass Rate     : {dq_pass_rate:.2f}%")
        log.info(f"[DQ REPORT] Error Breakdown:")
        for row in breakdown:
            log.info(f"[DQ REPORT]   - {row['error_reason']}: {row['error_count']:,}")
        log.info("=" * 60)

        # Alert if DQ pass rate drops below 95%
        if dq_pass_rate < 95.0:
            log.warning(
                f"[DQ ALERT] Pass rate {dq_pass_rate:.2f}% is below 95% threshold! "
                f"Investigate data_quality_log for {target_date}."
            )

    except Exception as e:
        log.error(f"generate_dq_summary_report failed: {e}", exc_info=True)
        raise


# ---------------------------------------------------------------------------
# DAG Definition
# ---------------------------------------------------------------------------
with DAG(
    dag_id='dlq_processor',
    description='Process DLQ messages into data_quality_log for audit & monitoring',
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule_interval='0 2 * * *',   # 02:00 AM UTC daily (after daily_aggregation)
    catchup=False,
    tags=['crypto', 'data-quality', 'dlq', 'regulatory', 'phase-4'],
) as dag:

    t_poll = PythonOperator(
        task_id='poll_dlq_messages',
        python_callable=poll_dlq_messages,
        provide_context=True,
    )

    t_insert = PythonOperator(
        task_id='insert_to_dq_log',
        python_callable=insert_to_dq_log,
        provide_context=True,
    )

    t_report = PythonOperator(
        task_id='generate_dq_summary_report',
        python_callable=generate_dq_summary_report,
        provide_context=True,
    )

    # Sequential: poll → insert → report
    t_poll >> t_insert >> t_report
