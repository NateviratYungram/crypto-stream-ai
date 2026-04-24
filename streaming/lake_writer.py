"""
CryptoStream AI — Data Lake Writer
===================================
Consumes Avro-encoded trades from Kafka (via Schema Registry) and writes
them as partitioned Parquet files to the local Data Lake.

Data Lake layout (Hive-style partitioning):
    datalake/raw/year=YYYY/month=MM/day=DD/trades_YYYYMMDD_HHMMSS.parquet

Flush policy: every FLUSH_RECORD_LIMIT records OR FLUSH_TIME_LIMIT seconds,
whichever comes first.
"""

import logging
import os
import time
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from confluent_kafka import Consumer, KafkaError, KafkaException
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer
from confluent_kafka.serialization import MessageField, SerializationContext

# ── Configuration ─────────────────────────────────────────────────────────────
KAFKA_BROKER        = os.environ.get("KAFKA_BROKER", "localhost:9092")
KAFKA_TOPIC         = "trade_stream"
KAFKA_GROUP_ID      = "lake_writer_v1"
SCHEMA_REGISTRY_URL = os.environ.get("SCHEMA_REGISTRY_URL", "http://localhost:8085")

_default_lake       = os.path.join(os.path.dirname(__file__), "..", "datalake", "raw")
DATALAKE_BASE_PATH  = os.environ.get("DATALAKE_OUTPUT_PATH", _default_lake)

FLUSH_RECORD_LIMIT  = int(os.environ.get("FLUSH_RECORD_LIMIT", 100))
FLUSH_TIME_LIMIT    = int(os.environ.get("FLUSH_TIME_LIMIT", 60))

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("lake_writer")

# ── Parquet schema ────────────────────────────────────────────────────────────
# price/quantity arrive as strings from Avro (decimal precision); cast to
# float64 during flush so downstream Spark/dbt can aggregate them directly.
PARQUET_SCHEMA = pa.schema([
    pa.field("trade_id",       pa.string()),
    pa.field("symbol",         pa.string()),
    pa.field("price",          pa.float64()),
    pa.field("quantity",       pa.float64()),
    pa.field("timestamp",      pa.int64()),
    pa.field("is_buyer_maker", pa.bool_()),
    pa.field("ingested_at",    pa.string()),
])


# ── Partition helpers ─────────────────────────────────────────────────────────

def _partition_path(dt: datetime) -> str:
    return os.path.join(
        DATALAKE_BASE_PATH,
        f"year={dt.year}",
        f"month={dt.month:02d}",
        f"day={dt.day:02d}",
    )


def _output_filename(dt: datetime) -> str:
    return f"trades_{dt.strftime('%Y%m%d_%H%M%S')}.parquet"


# ── Flush ─────────────────────────────────────────────────────────────────────

def flush_to_parquet(records: list, flush_time: datetime) -> None:
    if not records:
        return

    df = pd.DataFrame(records)

    for field in PARQUET_SCHEMA:
        if field.name not in df.columns:
            df[field.name] = None

    df = df[[f.name for f in PARQUET_SCHEMA]]
    df["price"]     = pd.to_numeric(df["price"],     errors="coerce")
    df["quantity"]  = pd.to_numeric(df["quantity"],  errors="coerce")
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").astype("Int64")

    partition_dir = _partition_path(flush_time)
    os.makedirs(partition_dir, exist_ok=True)
    out = os.path.join(partition_dir, _output_filename(flush_time))

    table = pa.Table.from_pandas(df, schema=PARQUET_SCHEMA, preserve_index=False)
    pq.write_table(table, out, compression="snappy")

    logger.info(
        "Flushed %d records → %s [%.1f KB]",
        len(records), out, os.path.getsize(out) / 1024,
    )


# ── Consumer setup ────────────────────────────────────────────────────────────

def _build_consumer() -> tuple[Consumer, AvroDeserializer]:
    registry    = SchemaRegistryClient({"url": SCHEMA_REGISTRY_URL})
    deserializer = AvroDeserializer(registry)
    consumer    = Consumer({
        "bootstrap.servers":       KAFKA_BROKER,
        "group.id":                KAFKA_GROUP_ID,
        "auto.offset.reset":       "latest",
        "enable.auto.commit":      True,
        "auto.commit.interval.ms": 5000,
    })
    logger.info("Kafka consumer created (broker=%s, registry=%s)", KAFKA_BROKER, SCHEMA_REGISTRY_URL)
    return consumer, deserializer


def _deserialize(msg, deserializer: AvroDeserializer) -> dict | None:
    try:
        ctx = SerializationContext(KAFKA_TOPIC, MessageField.VALUE)
        return deserializer(msg.value(), ctx)
    except Exception as exc:
        logger.warning("Avro deserialization failed: %s", exc)
        return None


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=" * 60)
    logger.info("CryptoStream AI — Data Lake Writer")
    logger.info("Output : %s", os.path.abspath(DATALAKE_BASE_PATH))
    logger.info("Flush  : %d records OR %ds", FLUSH_RECORD_LIMIT, FLUSH_TIME_LIMIT)
    logger.info("=" * 60)

    os.makedirs(DATALAKE_BASE_PATH, exist_ok=True)
    consumer, deserializer = _build_consumer()
    consumer.subscribe([KAFKA_TOPIC])

    buffer     = []
    last_flush = time.time()

    try:
        while True:
            msg = consumer.poll(timeout=1.0)

            if msg is None:
                if buffer and (time.time() - last_flush) >= FLUSH_TIME_LIMIT:
                    flush_to_parquet(buffer, datetime.now(timezone.utc))
                    buffer     = []
                    last_flush = time.time()
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(msg.error())

            record = _deserialize(msg, deserializer)
            if record is None:
                continue

            buffer.append(record)

            elapsed          = time.time() - last_flush
            record_limit_hit = len(buffer) >= FLUSH_RECORD_LIMIT
            time_limit_hit   = elapsed >= FLUSH_TIME_LIMIT

            if record_limit_hit or time_limit_hit:
                trigger = "record_limit" if record_limit_hit else "time_limit"
                logger.info(
                    "Flush [%s] | buffer=%d | elapsed=%.0fs",
                    trigger, len(buffer), elapsed,
                )
                flush_to_parquet(buffer, datetime.now(timezone.utc))
                buffer     = []
                last_flush = time.time()

    except KeyboardInterrupt:
        logger.info("Shutdown received.")
        if buffer:
            logger.info("Flushing %d remaining records...", len(buffer))
            flush_to_parquet(buffer, datetime.now(timezone.utc))
        logger.info("Data Lake Writer stopped gracefully.")

    except Exception as exc:
        logger.error("Unexpected error: %s", exc, exc_info=True)
        raise

    finally:
        consumer.close()
        logger.info("Kafka consumer closed.")


if __name__ == "__main__":
    main()
