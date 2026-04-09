"""
CryptoStream AI - Phase 3B: Data Lake Writer
=============================================
Consumes trades from Kafka and writes them as partitioned Parquet files
to the local Data Lake directory.

Banking Relevance:
    - Parquet + Date Partitioning mirrors how Thai banks store Transaction
      History for Regulatory Reporting (BOT Monthly Report, Annual Archive).
    - Partitioned layout enables fast historical queries with Spark/Athena
      without scanning the full dataset — critical for audit investigations.

Data Lake Structure:
    datalake/
    └── raw/
        └── year=YYYY/
            └── month=MM/
                └── day=DD/
                    └── trades_YYYYMMDD_HHMMSS.parquet

Flush Policy (Micro-batch):
    - Every 5 minutes OR 1,000 records (whichever comes first)
    - Provides a balance between latency and file size efficiency
"""

import os
import logging
import json
import time
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from kafka import KafkaConsumer
from kafka.errors import KafkaError

# ---------------------------------------------------------------------------
# Configuration
# Environment variables allow the same script to run on localhost OR inside
# the Docker 'lake-writer' container without any code changes.
# ---------------------------------------------------------------------------
KAFKA_BROKER        = os.environ.get('KAFKA_BROKER', 'localhost:9092')
KAFKA_TOPIC         = 'trade_stream'
KAFKA_GROUP_ID      = 'lake_writer_v1'

# Docker service mounts datalake/ to /opt/datalake_output.
# When running locally, falls back to the relative datalake/raw/ path.
_default_lake_path  = os.path.join(os.path.dirname(__file__), '..', 'datalake', 'raw')
DATALAKE_BASE_PATH  = os.environ.get('DATALAKE_OUTPUT_PATH', _default_lake_path)

# Flush policy: write parquet file after N records OR N seconds
# For production hardening, we allow these to be overridden via env vars.
FLUSH_RECORD_LIMIT  = int(os.environ.get('FLUSH_RECORD_LIMIT', 100))  # records
FLUSH_TIME_LIMIT    = int(os.environ.get('FLUSH_TIME_LIMIT', 60))    # seconds (1 minute)

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)
logger = logging.getLogger("lake_writer")

# ---------------------------------------------------------------------------
# Parquet Schema Definition
# Banking: Explicit schema prevents type drift across files (schema evolution
# issues cause failures in downstream Spark/Regulatory reporting jobs).
# ---------------------------------------------------------------------------
PARQUET_SCHEMA = pa.schema([
    pa.field("trade_id",       pa.string()),
    pa.field("symbol",         pa.string()),
    pa.field("price",          pa.float64()),
    pa.field("quantity",       pa.float64()),
    pa.field("timestamp",      pa.int64()),
    pa.field("is_buyer_maker", pa.bool_()),
    pa.field("ingested_at",    pa.string()),   # ISO8601 UTC string
])


def get_partition_path(dt: datetime) -> str:
    """
    Returns the Hive-style partition directory path for a given datetime.
    Example: datalake/raw/year=2026/month=02/day=24/
    """
    return os.path.join(
        DATALAKE_BASE_PATH,
        f"year={dt.year}",
        f"month={dt.month:02d}",
        f"day={dt.day:02d}"
    )


def get_output_filename(dt: datetime) -> str:
    """
    Returns a timestamped filename for the Parquet file.
    Example: trades_20260224_140000.parquet
    """
    return f"trades_{dt.strftime('%Y%m%d_%H%M%S')}.parquet"


def flush_to_parquet(records: list, flush_time: datetime) -> None:
    """
    Converts accumulated records to a Parquet file and writes to Data Lake.
    Uses explicit schema to enforce type consistency across all files.

    Args:
        records:    List of trade dicts accumulated since last flush
        flush_time: Datetime used to determine partition path
    """
    if not records:
        logger.info("flush_to_parquet called with empty records — skipping.")
        return

    try:
        # Convert to pandas DataFrame
        df = pd.DataFrame(records)

        # Ensure all expected columns exist (defensive programming)
        for field in PARQUET_SCHEMA:
            if field.name not in df.columns:
                df[field.name] = None

        # Select and order columns to match schema strictly
        df = df[[field.name for field in PARQUET_SCHEMA]]

        # Cast types explicitly to match PyArrow schema
        df['trade_id'] = df['trade_id'].astype(str)
        df['price']    = pd.to_numeric(df['price'],    errors='coerce')
        df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce')
        df['timestamp']= pd.to_numeric(df['timestamp'],errors='coerce').astype('Int64')

        # Determine partition path and filename
        partition_dir = get_partition_path(flush_time)
        os.makedirs(partition_dir, exist_ok=True)
        output_path = os.path.join(partition_dir, get_output_filename(flush_time))

        # Write Parquet with snappy compression (good balance of speed vs size)
        table = pa.Table.from_pandas(df, schema=PARQUET_SCHEMA, preserve_index=False)
        pq.write_table(table, output_path, compression='snappy')

        logger.info(
            f"Flushed {len(records):,} records to Parquet: {output_path} "
            f"[{os.path.getsize(output_path) / 1024:.1f} KB]"
        )

    except Exception as e:
        logger.error(f"Failed to write Parquet file: {e}", exc_info=True)
        # In production: send alert to PagerDuty / monitoring system
        raise


def parse_message(raw_message: bytes) -> dict | None:
    """
    Safely parse a raw Kafka JSON message into a dict.
    Returns None if parsing fails (malformed JSON).
    """
    try:
        data = json.loads(raw_message.decode('utf-8'))
        data['ingested_at'] = datetime.now(timezone.utc).isoformat()
        return data
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raw_preview = str(raw_message)[:200]
        logger.warning(f"Failed to parse message: {e} | Raw: {raw_preview}")
        return None


def get_kafka_consumer() -> KafkaConsumer:
    """
    Creates and returns a KafkaConsumer with retry logic.
    """
    while True:
        try:
            consumer = KafkaConsumer(
                KAFKA_TOPIC,
                bootstrap_servers=[KAFKA_BROKER],
                group_id=KAFKA_GROUP_ID,
                auto_offset_reset='latest',        # Start from latest on first run
                enable_auto_commit=True,
                auto_commit_interval_ms=5000,
                value_deserializer=lambda x: x,   # Keep raw bytes, parse manually
                api_version=(0, 10, 1)
            )
            logger.info(f"Connected to Kafka broker: {KAFKA_BROKER}")
            return consumer
        except KafkaError as e:
            logger.error(f"Kafka connection failed: {e}. Retrying in 10 seconds...")
            time.sleep(10)


def main():
    logger.info("=" * 60)
    logger.info("CryptoStream AI — Data Lake Writer (Phase 3B)")
    logger.info(f"Output path  : {os.path.abspath(DATALAKE_BASE_PATH)}")
    logger.info(f"Flush limit  : {FLUSH_RECORD_LIMIT:,} records OR {FLUSH_TIME_LIMIT}s")
    logger.info("=" * 60)

    # Create base datalake directory if not exists
    os.makedirs(DATALAKE_BASE_PATH, exist_ok=True)

    consumer = get_kafka_consumer()

    buffer      = []          # In-memory batch buffer
    last_flush  = time.time() # Timestamp of last flush

    logger.info(f"Listening on Kafka topic: '{KAFKA_TOPIC}' ...")

    try:
        for message in consumer:
            # Parse raw Kafka message
            record = parse_message(message.value)
            if record is None:
                continue  # Skip unparseable messages

            buffer.append(record)

            # Check flush conditions
            time_since_flush    = time.time() - last_flush
            record_limit_hit    = len(buffer) >= FLUSH_RECORD_LIMIT
            time_limit_hit      = time_since_flush >= FLUSH_TIME_LIMIT

            if record_limit_hit or time_limit_hit:
                trigger = "record_limit" if record_limit_hit else "time_limit"
                logger.info(
                    f"Flush triggered by [{trigger}] | "
                    f"buffer={len(buffer):,} records | "
                    f"elapsed={time_since_flush:.0f}s"
                )
                flush_to_parquet(buffer, datetime.now(timezone.utc))
                buffer      = []           # Reset buffer after flush
                last_flush  = time.time() # Reset timer

    except KeyboardInterrupt:
        logger.info("Shutdown signal received (KeyboardInterrupt).")
        # Flush remaining records in buffer before exiting — important for data completeness
        if buffer:
            logger.info(f"Flushing {len(buffer):,} remaining records before shutdown...")
            flush_to_parquet(buffer, datetime.now(timezone.utc))
        logger.info("Data Lake Writer stopped gracefully.")

    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
        raise

    finally:
        consumer.close()
        logger.info("Kafka consumer closed.")


if __name__ == '__main__':
    main()
