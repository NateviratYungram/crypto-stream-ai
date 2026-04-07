"""
CryptoStream AI - Phase 2 & 3: Real-time Flink Streaming Processor
====================================================================
Phase 2: Whale Detection, VWAP Aggregation (1-min Tumbling Window)
Phase 3: Data Quality Validation Layer with Dead Letter Queue (DLQ)

Banking Relevance:
    - DLQ pattern mirrors Production systems used in Payment Reconciliation
      (e.g., BAHTNET, PromptPay) where invalid records must NEVER be silently
      dropped or mixed with clean data. They must be isolated and auditable.
    - data_quality_log table provides Audit Trail required by ธปท. / AMLO.

Architecture (Phase 3):
    Kafka (trade_stream)
        |
        v
    [Flink Validation Gate]
        |-- VALID   --> enriched_trades (PostgreSQL)
        |               market_metrics (PostgreSQL)  [1-min VWAP]
        |-- INVALID --> trade_stream_dlq (Kafka DLQ)
        |               data_quality_log (PostgreSQL)  [Real-time Audit]
"""

import logging
from pyflink.datastream import StreamExecutionEnvironment, TimeCharacteristic
from pyflink.table import StreamTableEnvironment, DataTypes, EnvironmentSettings
from pyflink.table.expressions import col, lit

# ---------------------------------------------------------------------------
# Logging Setup — always use structured logging in production
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)
logger = logging.getLogger("flink_processor")


def main():
    logger.info("Starting CryptoStream AI Flink Processor (Phase 3 — Data Quality)")

    # -----------------------------------------------------------------------
    # 1. Setup Flink Environment
    # -----------------------------------------------------------------------
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(1)
    env.set_stream_time_characteristic(TimeCharacteristic.EventTime)

    settings = EnvironmentSettings.new_instance().in_streaming_mode().build()
    t_env = StreamTableEnvironment.create(env, environment_settings=settings)

    logger.info("Flink StreamTableEnvironment initialized.")

    # -----------------------------------------------------------------------
    # 2. SOURCE: Kafka — trade_stream (Raw input, may contain dirty data)
    # -----------------------------------------------------------------------
    logger.info("Registering SOURCE: Kafka topic 'trade_stream'")
    t_env.execute_sql("""
        CREATE TABLE trade_stream (
            symbol          STRING,
            price           DECIMAL(20, 8),
            quantity        DECIMAL(20, 8),
            `timestamp`     BIGINT,
            trade_id        STRING,
            is_buyer_maker  BOOLEAN,
            -- Computed columns for time-based windowing
            ts              AS TO_TIMESTAMP_LTZ(`timestamp`, 3),
            WATERMARK FOR ts AS ts - INTERVAL '5' SECOND
        ) WITH (
            'connector'                     = 'kafka',
            'topic'                         = 'trade_stream',
            'properties.bootstrap.servers'  = 'kafka:29092',
            'properties.group.id'           = 'flink_processor_v3',
            'scan.startup.mode'             = 'latest-offset',
            'format'                        = 'json',
            'json.ignore-parse-errors'      = 'true'
        )
    """)

    # -----------------------------------------------------------------------
    # 3. SINK: Dead Letter Queue (DLQ) — Kafka topic for invalid records
    #    Banking: Invalid records are NEVER dropped silently. They are routed
    #    to DLQ for investigation and regulatory audit purposes.
    # -----------------------------------------------------------------------
    logger.info("Registering SINK: Kafka DLQ topic 'trade_stream_dlq'")
    t_env.execute_sql("""
        CREATE TABLE trade_stream_dlq (
            trade_id        STRING,
            symbol          STRING,
            price           DECIMAL(20, 8),
            quantity        DECIMAL(20, 8),
            `timestamp`     BIGINT,
            is_buyer_maker  BOOLEAN,
            error_reason    STRING
        ) WITH (
            'connector'                     = 'kafka',
            'topic'                         = 'trade_stream_dlq',
            'properties.bootstrap.servers'  = 'kafka:29092',
            'format'                        = 'json'
        )
    """)

    # -----------------------------------------------------------------------
    # 4. SINK: PostgreSQL — enriched_trades (Clean records only)
    # -----------------------------------------------------------------------
    logger.info("Registering SINK: PostgreSQL table 'enriched_trades'")
    t_env.execute_sql("""
        CREATE TABLE enriched_trades (
            trade_id        BIGINT,
            symbol          STRING,
            price           DECIMAL(20, 8),
            quantity        DECIMAL(20, 8),
            `timestamp`     BIGINT,
            is_buyer_maker  BOOLEAN,
            is_whale        BOOLEAN,
            PRIMARY KEY (trade_id) NOT ENFORCED
        ) WITH (
            'connector'     = 'jdbc',
            'url'           = 'jdbc:postgresql://postgres:5432/crypto_stream_db',
            'table-name'    = 'enriched_trades',
            'username'      = 'user',
            'password'      = 'password'
        )
    """)

    # -----------------------------------------------------------------------
    # 5. SINK: PostgreSQL — market_metrics (1-min VWAP aggregates)
    # -----------------------------------------------------------------------
    logger.info("Registering SINK: PostgreSQL table 'market_metrics'")
    t_env.execute_sql("""
        CREATE TABLE market_metrics (
            window_start    TIMESTAMP(3),
            window_end      TIMESTAMP(3),
            symbol          STRING,
            avg_price       DECIMAL(20, 8),
            total_volume    DECIMAL(20, 8),
            trade_count     BIGINT,
            PRIMARY KEY (window_start, symbol) NOT ENFORCED
        ) WITH (
            'connector'     = 'jdbc',
            'url'           = 'jdbc:postgresql://postgres:5432/crypto_stream_db',
            'table-name'    = 'market_metrics',
            'username'      = 'user',
            'password'      = 'password'
        )
    """)

    # -----------------------------------------------------------------------
    # 5.1 SINK: PostgreSQL — data_quality_log (Real-time Audit Trail)
    #    Banking: Provides immediate visibility into DQ failures.
    # -----------------------------------------------------------------------
    logger.info("Registering SINK: PostgreSQL table 'data_quality_log'")
    t_env.execute_sql("""
        CREATE TABLE data_quality_log_sink (
            trade_id        STRING,
            error_reason    STRING,
            raw_payload     STRING
        ) WITH (
            'connector'     = 'jdbc',
            'url'           = 'jdbc:postgresql://postgres:5432/crypto_stream_db',
            'table-name'    = 'data_quality_log',
            'username'      = 'user',
            'password'      = 'password'
        )
    """)


    # -----------------------------------------------------------------------
    # 6. DATA QUALITY VALIDATION (Phase 3 — Core Logic)
    #    Rules (mirrors basic Financial Data Quality standards):
    #      - price must not be NULL and must be > 0
    #      - quantity must not be NULL and must be > 0
    #      - symbol must not be NULL
    #      - trade_id must not be NULL
    #
    #    Implementation: Use Flink SQL CASE WHEN to tag each record,
    #    then split into two streams: valid_trades and invalid_trades.
    # -----------------------------------------------------------------------
    logger.info("Applying Data Quality validation rules...")

    # Step 1: Tag every record with error_reason (NULL if clean)
    t_env.execute_sql("""
        CREATE VIEW tagged_trades AS
        SELECT
            trade_id,
            symbol,
            price,
            quantity,
            `timestamp`,
            is_buyer_maker,
            ts,
            CASE
                WHEN trade_id IS NULL                       THEN 'null_trade_id'
                WHEN symbol IS NULL                         THEN 'null_symbol'
                WHEN price IS NULL OR price <= 0            THEN 'invalid_price'
                WHEN quantity IS NULL OR quantity <= 0      THEN 'invalid_quantity'
                ELSE NULL   -- NULL error_reason = VALID record
            END AS error_reason
        FROM trade_stream
    """)

    # Step 2: VALID records — only rows where error_reason IS NULL
    t_env.execute_sql("""
        CREATE VIEW valid_trades AS
        SELECT trade_id, symbol, price, quantity, `timestamp`, is_buyer_maker, ts
        FROM tagged_trades
        WHERE error_reason IS NULL
    """)

    # Step 3: INVALID records — route to DLQ
    t_env.execute_sql("""
        CREATE VIEW invalid_trades AS
        SELECT trade_id, symbol, price, quantity, `timestamp`, is_buyer_maker, error_reason
        FROM tagged_trades
        WHERE error_reason IS NOT NULL
    """)

    # Step 4: Prepare JSON payload for Postgres Audit Sink
    # We construct a simple JSON string from the fields
    t_env.execute_sql("""
        CREATE VIEW invalid_trades_json AS
        SELECT
            trade_id,
            error_reason,
            '{"trade_id":"' || COALESCE(trade_id, 'null') ||
            '","symbol":"' || COALESCE(symbol, 'null') ||
            '","price":' || CAST(COALESCE(price, 0) AS STRING) ||
            ',"quantity":' || CAST(COALESCE(quantity, 0) AS STRING) ||
            ',"timestamp":' || CAST(COALESCE(`timestamp`, 0) AS STRING) || '}' as raw_payload
        FROM invalid_trades
    """)

    logger.info("Data Quality views created: tagged_trades, valid_trades, invalid_trades, invalid_trades_json")


    # -----------------------------------------------------------------------
    # 7. WHALE DETECTION + ENRICHMENT (Phase 2, applied on valid_trades only)
    #    Whale = quantity > 0.5 BTC — significant market mover detection
    #    Banking: Mirrors AML transaction monitoring thresholds
    # -----------------------------------------------------------------------
    t_env.execute_sql("""
        CREATE VIEW enriched_valid_trades AS
        SELECT
            CAST(trade_id AS BIGINT)    AS trade_id,
            symbol,
            price,
            quantity,
            `timestamp`,
            is_buyer_maker,
            (quantity > 0.5)            AS is_whale,
            ts
        FROM valid_trades
    """)

    # -----------------------------------------------------------------------
    # 8. EXECUTE: Submit both sinks as a single Flink job (StatementSet)
    #    StatementSet ensures all sinks run in ONE job submission — important
    #    for resource efficiency and consistent watermark handling.
    # -----------------------------------------------------------------------
    logger.info("Building StatementSet for multi-sink job submission...")

    statement_set = t_env.create_statement_set()

    # Sink 1: enriched_trades (all valid trades, with whale flag)
    statement_set.add_insert_sql("""
        INSERT INTO enriched_trades
        SELECT trade_id, symbol, price, quantity, `timestamp`, is_buyer_maker, is_whale
        FROM enriched_valid_trades
    """)

    # Sink 2: market_metrics (1-minute VWAP tumbling window on valid trades)
    # VWAP = Volume Weighted Average Price = Σ(price × qty) / Σ(qty)
    # Banking: VWAP is the standard benchmark for execution quality reporting
    statement_set.add_insert_sql("""
        INSERT INTO market_metrics
        SELECT
            window_start,
            window_end,
            symbol,
            SUM(price * quantity) / SUM(quantity)   AS avg_price,
            SUM(quantity)                            AS total_volume,
            COUNT(trade_id)                          AS trade_count
        FROM TABLE(
            TUMBLE(TABLE enriched_valid_trades, DESCRIPTOR(ts), INTERVAL '1' MINUTE)
        )
        GROUP BY window_start, window_end, symbol
    """)

    # Sink 3: DLQ — invalid records to Kafka DLQ topic
    #    Banking: Invalid records are NEVER dropped silently. They are routed
    #    to the Kafka DLQ for investigation and separate audit persistence.
    statement_set.add_insert_sql("""
        INSERT INTO trade_stream_dlq
        SELECT trade_id, symbol, price, quantity, `timestamp`, is_buyer_maker, error_reason
        FROM invalid_trades
    """)

    # Sink 4: Postgres Audit Log — real-time DQ visibility for AI Agent (MCP)
    #    Banking: Provides immediate, queryable audit trail for regulators.
    statement_set.add_insert_sql("""
        INSERT INTO data_quality_log_sink
        SELECT trade_id, error_reason, raw_payload
        FROM invalid_trades_json
    """)

    logger.info("Submitting Flink job with 4 sinks: enriched_trades, market_metrics, trade_stream_dlq, data_quality_log")

    # Execute — this is a blocking call, the job runs indefinitely
    # The returned TableResult is used for monitoring / cancellation
    result = statement_set.execute()

    logger.info("Flink job submitted successfully. Job ID: %s", result.get_job_client().get_job_id() if result.get_job_client() else "N/A")
    logger.info("Monitoring  : Flink UI  -> http://localhost:8081")
    logger.info("DLQ Monitor : Kafka UI  -> http://localhost:8080  (topic: trade_stream_dlq)")
    logger.info("DQ Audit    : PostgreSQL -> SELECT * FROM data_quality_log ORDER BY detected_at DESC LIMIT 20;")


if __name__ == '__main__':
    main()
