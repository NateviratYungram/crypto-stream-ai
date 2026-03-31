"""
CryptoStream AI — Airflow DAG: Daily Trade Aggregation
=======================================================
DAG ID   : daily_aggregation
Schedule : 01:00 AM daily (after midnight, all trades for 'yesterday' are settled)
Purpose  : Computes daily OHLCV + Whale Summary from enriched_trades
           and upserts the result into daily_summary table.

Banking Relevance:
    This DAG mirrors the "EOD (End-of-Day) Batch" process in Thai banks:
    - After market close, all transactions are aggregated into daily totals.
    - The output (daily_summary) is the equivalent of a "Daily Position Report"
      submitted to ธปท. (Bank of Thailand) for regulatory oversight.
    - Using Airflow ensures the job is: scheduled, retried on failure,
      observable via UI, and auditable via logs — all requirements for
      production regulatory reporting systems.

Task Flow:
    check_data_availability
            ↓
    [compute_daily_ohlcv] → [compute_whale_summary]
            ↓                         ↓
            └──── upsert_daily_summary ────┘
                        ↓
                log_completion
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras

from airflow import DAG
from airflow.operators.python import PythonOperator, ShortCircuitOperator

# ---------------------------------------------------------------------------
# DAG Default Arguments
# ---------------------------------------------------------------------------
DEFAULT_ARGS = {
    'owner'           : 'data-engineering-team',
    'depends_on_past' : False,
    'email_on_failure': False,
    'email_on_retry'  : False,
    'retries'         : 3,
    'retry_delay'     : timedelta(minutes=5),
}

# ---------------------------------------------------------------------------
# Database Connection
# ---------------------------------------------------------------------------
DB_CONFIG = {
    'host'    : 'postgres',
    'port'    : 5432,
    'dbname'  : 'crypto_stream_db',
    'user'    : 'user',
    'password': 'password',
}

SYMBOL = 'BTCUSDT'  # Primary symbol tracked

log = logging.getLogger(__name__)


def get_conn():
    """Returns a psycopg2 connection to crypto_stream_db."""
    return psycopg2.connect(**DB_CONFIG)


# ---------------------------------------------------------------------------
# Task Functions
# ---------------------------------------------------------------------------

def check_data_availability(**context) -> bool:
    """
    ShortCircuit Task: Check if there are any trades for the target date.
    If no data exists, skip the rest of the DAG gracefully (not a failure).

    In banking: equivalent to "Does today's batch file exist?" check
    before starting reconciliation.
    """
    # Airflow passes 'data_interval_start' as the logical date of the run
    # We process 'yesterday' data when running at 01:00 today
    target_date = context['data_interval_start'].date()
    log.info(f"Checking data availability for report_date: {target_date}")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*)
                    FROM enriched_trades
                    WHERE DATE(TO_TIMESTAMP(timestamp / 1000.0) AT TIME ZONE 'UTC') = %s
                """, (target_date,))
                count = cur.fetchone()[0]

        log.info(f"Found {count:,} trades for {target_date}")

        if count == 0:
            log.warning(f"No trades found for {target_date} — skipping DAG run.")
            return False  # Short-circuit: skip downstream tasks

        return True

    except Exception as e:
        log.error(f"check_data_availability failed: {e}", exc_info=True)
        raise


def compute_daily_ohlcv(**context) -> dict:
    """
    Compute OHLCV (Open, High, Low, Close, Volume) for the target date.
    OHLCV is the standard financial data format used in all market data systems.

    Banking: OHLCV data is used in:
    - Daily Market Risk Reports
    - VaR (Value at Risk) calculations
    - Price discovery audit trails
    """
    target_date = context['data_interval_start'].date()
    log.info(f"Computing OHLCV for {target_date}...")

    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    WITH ordered_trades AS (
                        SELECT
                            price,
                            quantity,
                            timestamp,
                            ROW_NUMBER() OVER (ORDER BY timestamp ASC)  AS rn_asc,
                            ROW_NUMBER() OVER (ORDER BY timestamp DESC) AS rn_desc
                        FROM enriched_trades
                        WHERE DATE(TO_TIMESTAMP(timestamp / 1000.0) AT TIME ZONE 'UTC') = %s
                    )
                    SELECT
                        MAX(price)  FILTER (WHERE rn_asc  = 1) AS open_price,
                        MAX(price)                              AS high_price,
                        MIN(price)                              AS low_price,
                        MAX(price)  FILTER (WHERE rn_desc = 1) AS close_price,
                        SUM(quantity)                           AS total_volume,
                        COUNT(*)                                AS trade_count
                    FROM ordered_trades
                """, (target_date,))

                result = dict(cur.fetchone())
                result['report_date'] = str(target_date)
                result['symbol']      = SYMBOL

        log.info(
            f"OHLCV computed: O={result['open_price']} H={result['high_price']} "
            f"L={result['low_price']} C={result['close_price']} "
            f"Vol={result['total_volume']} Count={result['trade_count']}"
        )

        # Push result to XCom for downstream task to merge
        context['ti'].xcom_push(key='ohlcv', value=result)
        return result

    except Exception as e:
        log.error(f"compute_daily_ohlcv failed: {e}", exc_info=True)
        raise


def compute_whale_summary(**context) -> dict:
    """
    Compute whale trade statistics for the target date.
    Whale trades (qty > 0.5 BTC) have outsized market impact.

    Banking: Analogous to "Large Value Transaction" monitoring —
    banks flag transactions above a threshold for AML review.
    """
    target_date = context['data_interval_start'].date()
    log.info(f"Computing whale summary for {target_date}...")

    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        COUNT(*)      AS whale_count,
                        COALESCE(SUM(quantity), 0) AS whale_volume
                    FROM enriched_trades
                    WHERE DATE(TO_TIMESTAMP(timestamp / 1000.0) AT TIME ZONE 'UTC') = %s
                      AND is_whale = TRUE
                """, (target_date,))

                result = dict(cur.fetchone())

        log.info(f"Whale summary: count={result['whale_count']}, volume={result['whale_volume']}")

        context['ti'].xcom_push(key='whale_summary', value=result)
        return result

    except Exception as e:
        log.error(f"compute_whale_summary failed: {e}", exc_info=True)
        raise


def upsert_daily_summary(**context):
    """
    Merge OHLCV and Whale data, then UPSERT into daily_summary table.
    Uses ON CONFLICT DO UPDATE (idempotent) — safe to re-run without duplication.

    Banking: Idempotency is critical in banking systems because:
    - EOD jobs must be re-runnable on failure without double-counting
    - Reconciliation requires deterministic, repeatable results
    """
    ti          = context['ti']
    ohlcv       = ti.xcom_pull(task_ids='compute_daily_ohlcv',   key='ohlcv')
    whale_stats = ti.xcom_pull(task_ids='compute_whale_summary',  key='whale_summary')

    if not ohlcv or not whale_stats:
        raise ValueError("Missing XCom data from upstream tasks — cannot proceed.")

    record = {
        'report_date' : ohlcv['report_date'],
        'symbol'      : ohlcv['symbol'],
        'open_price'  : ohlcv['open_price'],
        'high_price'  : ohlcv['high_price'],
        'low_price'   : ohlcv['low_price'],
        'close_price' : ohlcv['close_price'],
        'total_volume': ohlcv['total_volume'],
        'trade_count' : ohlcv['trade_count'],
        'whale_count' : whale_stats['whale_count'],
        'whale_volume': whale_stats['whale_volume'],
    }

    log.info(f"Upserting daily_summary for {record['report_date']} / {record['symbol']}")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO daily_summary (
                        report_date, symbol,
                        open_price, high_price, low_price, close_price,
                        total_volume, trade_count,
                        whale_count, whale_volume
                    ) VALUES (
                        %(report_date)s, %(symbol)s,
                        %(open_price)s,  %(high_price)s, %(low_price)s, %(close_price)s,
                        %(total_volume)s, %(trade_count)s,
                        %(whale_count)s, %(whale_volume)s
                    )
                    ON CONFLICT (report_date, symbol)
                    DO UPDATE SET
                        open_price   = EXCLUDED.open_price,
                        high_price   = EXCLUDED.high_price,
                        low_price    = EXCLUDED.low_price,
                        close_price  = EXCLUDED.close_price,
                        total_volume = EXCLUDED.total_volume,
                        trade_count  = EXCLUDED.trade_count,
                        whale_count  = EXCLUDED.whale_count,
                        whale_volume = EXCLUDED.whale_volume,
                        created_at   = CURRENT_TIMESTAMP
                """, record)
            conn.commit()

        log.info(f"daily_summary upserted successfully for {record['report_date']}")

    except Exception as e:
        log.error(f"upsert_daily_summary failed: {e}", exc_info=True)
        raise


def log_completion(**context):
    """Log a completion summary — acts as a lightweight audit record."""
    target_date = context['data_interval_start'].date()
    run_id      = context['run_id']
    log.info("=" * 60)
    log.info(f"[AUDIT] DAG: daily_aggregation | Status: SUCCESS")
    log.info(f"[AUDIT] report_date : {target_date}")
    log.info(f"[AUDIT] run_id      : {run_id}")
    log.info(f"[AUDIT] completed_at: {datetime.utcnow().isoformat()}Z")
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# DAG Definition
# ---------------------------------------------------------------------------
with DAG(
    dag_id='daily_aggregation',
    description='Daily OHLCV + Whale Summary aggregation (EOD Report)',
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule_interval='0 1 * * *',   # 01:00 AM UTC daily
    catchup=False,
    tags=['crypto', 'aggregation', 'regulatory', 'phase-4'],
) as dag:

    t_check = ShortCircuitOperator(
        task_id='check_data_availability',
        python_callable=check_data_availability,
        provide_context=True,
    )

    t_ohlcv = PythonOperator(
        task_id='compute_daily_ohlcv',
        python_callable=compute_daily_ohlcv,
        provide_context=True,
    )

    t_whale = PythonOperator(
        task_id='compute_whale_summary',
        python_callable=compute_whale_summary,
        provide_context=True,
    )

    t_upsert = PythonOperator(
        task_id='upsert_daily_summary',
        python_callable=upsert_daily_summary,
        provide_context=True,
    )

    t_log = PythonOperator(
        task_id='log_completion',
        python_callable=log_completion,
        provide_context=True,
    )

    # Task dependencies: check → [ohlcv ∥ whale] → upsert → log
    t_check >> [t_ohlcv, t_whale] >> t_upsert >> t_log
