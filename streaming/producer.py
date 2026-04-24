"""
CryptoStream AI — Kafka Producer (Avro + Schema Registry)
==========================================================
Streams live BTC/USDT trades from Binance WebSocket into the
trade_stream Kafka topic, serialized as Avro using the Confluent
Schema Registry.

Why Avro over plain JSON:
  - Schema Registry enforces a contract: consumers (Flink, lake-writer)
    cannot accidentally consume malformed messages after a producer change.
  - Binary Avro payloads are ~5× smaller than equivalent JSON.
  - Schema evolution (adding nullable fields) is backward-compatible —
    old consumers keep working without redeployment.

The Avro schema is defined in schemas/trade_event.avsc and registered
automatically on first run. Schema ID is prepended to every message so
consumers can fetch the correct schema version from the registry.
"""

import json
import logging
import os
import time
import websocket

from confluent_kafka import Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import SerializationContext, MessageField

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (overridable via environment variables)
# ---------------------------------------------------------------------------
KAFKA_BROKER          = os.environ.get("KAFKA_BROKER",          "localhost:9092")
SCHEMA_REGISTRY_URL   = os.environ.get("SCHEMA_REGISTRY_URL",   "http://localhost:8085")
KAFKA_TOPIC           = "trade_stream"
BINANCE_WS_URL        = "wss://stream.binance.com:9443/ws/btcusdt@trade"

# Avro schema path (relative to repo root; mounted at /opt in Docker)
_HERE = os.path.dirname(os.path.abspath(__file__))
AVRO_SCHEMA_PATH = os.path.join(_HERE, "..", "schemas", "trade_event.avsc")

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
_producer: Producer = None
_avro_serializer: AvroSerializer = None
message_count = 0


def _load_avro_schema() -> str:
    """Read Avro schema JSON from disk."""
    with open(AVRO_SCHEMA_PATH, "r") as fh:
        return fh.read()


def _build_producer() -> tuple:
    """
    Initialise Confluent Kafka producer + Avro serializer.
    Returns (producer, avro_serializer).
    """
    schema_str = _load_avro_schema()

    registry_client = SchemaRegistryClient({"url": SCHEMA_REGISTRY_URL})
    avro_serializer = AvroSerializer(
        registry_client,
        schema_str,
        # Map Python dict keys to Avro field names (1:1 — no transformation needed)
        to_dict=lambda obj, _ctx: obj,
    )

    producer = Producer({"bootstrap.servers": KAFKA_BROKER})
    logger.info("Kafka producer connected to %s", KAFKA_BROKER)
    logger.info("Schema Registry connected to %s", SCHEMA_REGISTRY_URL)
    return producer, avro_serializer


def _delivery_report(err, msg):
    """Callback invoked by Kafka producer after each message delivery."""
    if err:
        logger.error("Delivery failed for trade %s: %s", msg.key(), err)


def on_message(ws, message):
    """Handle a raw Binance WebSocket trade event."""
    global message_count

    try:
        raw = json.loads(message)

        # Build a dict that matches every field in trade_event.avsc
        record = {
            "trade_id":       str(raw["t"]),
            "symbol":         raw["s"],
            "price":          str(raw["p"]),   # Avro decimal fields sent as string
            "quantity":       str(raw["q"]),
            "timestamp":      int(raw["T"]),
            "is_buyer_maker": bool(raw["m"]),
            "ingested_at":    time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        }

        serialized = _avro_serializer(
            record,
            SerializationContext(KAFKA_TOPIC, MessageField.VALUE),
        )

        _producer.produce(
            topic=KAFKA_TOPIC,
            key=record["trade_id"],
            value=serialized,
            on_delivery=_delivery_report,
        )
        # poll() triggers delivery callbacks without blocking the WebSocket loop
        _producer.poll(0)

        message_count += 1
        if message_count % 100 == 0:
            logger.info(
                "Sent %d messages | last price: %s | symbol: %s",
                message_count, record["price"], record["symbol"],
            )

    except Exception as exc:
        logger.error("Error processing message: %s", exc, exc_info=True)


def on_error(ws, error):
    logger.error("WebSocket error: %s", error)


def on_close(ws, close_status_code, close_msg):
    logger.info("WebSocket closed (status=%s)", close_status_code)
    if _producer:
        _producer.flush()


def on_open(ws):
    logger.info("WebSocket opened — streaming %s", BINANCE_WS_URL)


def main():
    global _producer, _avro_serializer

    _producer, _avro_serializer = _build_producer()

    ws = websocket.WebSocketApp(
        BINANCE_WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    try:
        ws.run_forever()
    except KeyboardInterrupt:
        logger.info("Stopping producer...")
    finally:
        if _producer:
            _producer.flush()


if __name__ == "__main__":
    main()
