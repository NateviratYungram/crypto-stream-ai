"""
Unit tests for Kafka producer (streaming/producer.py).

Tests Binance WebSocket message parsing and Avro record construction.
No Kafka broker, Schema Registry, or network connection required —
_producer and _avro_serializer are replaced with lightweight stubs.
"""
import json
import re
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from streaming import producer as prod

# Minimal Binance trade WebSocket message (all required fields)
_BINANCE_MSG = json.dumps({
    "t": 12345678,            # trade_id (int from Binance)
    "s": "BTCUSDT",           # symbol
    "p": "67500.12000000",    # price (string from Binance)
    "q": "0.00150000",        # quantity (string from Binance)
    "T": 1700000000000,       # timestamp ms
    "m": False,               # is_buyer_maker
})

# Every field declared in schemas/trade_event.avsc
_AVRO_FIELDS = {
    "trade_id", "symbol", "price", "quantity",
    "timestamp", "is_buyer_maker", "ingested_at",
}


@pytest.fixture(autouse=True)
def reset_producer_state():
    """Swap real Kafka/Avro objects for stubs before each test."""
    prod._producer = MagicMock()
    prod._avro_serializer = MagicMock(return_value=b"serialized")
    prod.message_count = 0
    yield
    prod.message_count = 0


def _capture_record() -> dict:
    """Run on_message and return the record dict passed to _avro_serializer."""
    captured = {}

    def _stub(record, _ctx):
        captured.update(record)
        return b"serialized"

    prod._avro_serializer = _stub
    prod.on_message(None, _BINANCE_MSG)
    return captured


# ── Schema compliance ────────────────────────────────────────────────────────

def test_record_contains_all_avro_fields():
    """Record must include every field declared in trade_event.avsc."""
    record = _capture_record()
    missing = _AVRO_FIELDS - record.keys()
    assert not missing, f"Record is missing Avro fields: {missing}"


def test_no_extra_unexpected_fields():
    """No undeclared fields should slip through to the serializer."""
    record = _capture_record()
    extra = record.keys() - _AVRO_FIELDS
    assert not extra, f"Record has undeclared fields: {extra}"


# ── Type contracts (Avro schema enforcement) ─────────────────────────────────

def test_trade_id_is_string():
    """trade_id is Avro type 'string' — must not be an int."""
    record = _capture_record()
    assert isinstance(record["trade_id"], str)


def test_timestamp_is_int():
    """timestamp is Avro type 'long' — must be an integer."""
    record = _capture_record()
    assert isinstance(record["timestamp"], int)


def test_is_buyer_maker_is_bool():
    """is_buyer_maker is Avro type 'boolean'."""
    record = _capture_record()
    assert isinstance(record["is_buyer_maker"], bool)


def test_price_is_decimal():
    """Avro decimal fields are kept as Decimal values for serializer precision."""
    record = _capture_record()
    assert isinstance(record["price"], Decimal)


def test_quantity_is_decimal():
    record = _capture_record()
    assert isinstance(record["quantity"], Decimal)


def test_ingested_at_matches_iso8601():
    """ingested_at format must match the doc string in trade_event.avsc."""
    record = _capture_record()
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
    assert re.match(pattern, record["ingested_at"]), (
        f"ingested_at '{record['ingested_at']}' does not match ISO 8601"
    )


# ── Field value correctness ──────────────────────────────────────────────────

def test_symbol_matches_binance_input():
    record = _capture_record()
    assert record["symbol"] == "BTCUSDT"


def test_trade_id_matches_binance_t_field():
    """trade_id must be a string representation of the Binance 't' field."""
    record = _capture_record()
    assert record["trade_id"] == "12345678"


# ── Counter and delivery behaviour ──────────────────────────────────────────

def test_message_count_increments_after_valid_message():
    prod.on_message(None, _BINANCE_MSG)
    assert prod.message_count == 1


def test_message_count_increments_across_multiple_messages():
    for _ in range(5):
        prod.on_message(None, _BINANCE_MSG)
    assert prod.message_count == 5


def test_produce_is_called_once_per_message():
    prod.on_message(None, _BINANCE_MSG)
    prod._producer.produce.assert_called_once()


def test_logs_every_hundredth_message(monkeypatch):
    prod.message_count = 99
    info_messages = []
    monkeypatch.setattr(prod.logger, "info", lambda *args, **kwargs: info_messages.append(args))

    prod.on_message(None, _BINANCE_MSG)

    assert prod.message_count == 100
    assert any("Sent %d messages | last price: %s | symbol: %s" in call[0] for call in info_messages)


# ── Fault tolerance ──────────────────────────────────────────────────────────

def test_invalid_json_does_not_raise():
    """A malformed WebSocket frame must not crash the listener loop."""
    prod.on_message(None, "not valid json {{{")  # must not raise


def test_missing_binance_field_does_not_raise():
    """A message missing the 't' field must not crash the listener."""
    incomplete = json.dumps({"s": "BTCUSDT", "p": "100.0"})
    prod.on_message(None, incomplete)  # must not raise


def test_message_count_unchanged_after_bad_message():
    """Failed messages must not increment the counter."""
    prod.on_message(None, "bad json")
    assert prod.message_count == 0


def test_load_avro_schema_reads_file(monkeypatch):
    monkeypatch.setattr(prod, "AVRO_SCHEMA_PATH", "fake.avsc")

    class FakeFile:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return '{"type":"record"}'

    monkeypatch.setattr("builtins.open", lambda path, mode: FakeFile())

    assert prod._load_avro_schema() == '{"type":"record"}'


def test_build_producer_creates_dependencies(monkeypatch):
    created = {}
    monkeypatch.setattr(prod, "_load_avro_schema", lambda: '{"type":"record"}')
    monkeypatch.setattr(
        prod,
        "SchemaRegistryClient",
        lambda config: created.setdefault("registry", config) or "registry-client",
    )
    monkeypatch.setattr(
        prod,
        "AvroSerializer",
        lambda client, schema, to_dict: created.setdefault(
            "serializer",
            {"client": client, "schema": schema, "mapped": to_dict({"a": 1}, None)},
        )
        or "serializer",
    )
    monkeypatch.setattr(prod, "Producer", lambda config: created.setdefault("producer", config) or "producer-client")

    producer, serializer = prod._build_producer()

    assert producer == {"bootstrap.servers": prod.KAFKA_BROKER}
    assert serializer["schema"] == '{"type":"record"}'
    assert created["registry"] == {"url": prod.SCHEMA_REGISTRY_URL}


def test_delivery_report_logs_only_on_error():
    prod._delivery_report(None, MagicMock())
    prod._delivery_report(RuntimeError("bad"), MagicMock(key=lambda: "123"))


def test_on_close_flushes_producer():
    prod.on_close(None, 1000, "closed")
    prod._producer.flush.assert_called_once()


def test_on_close_without_producer_does_not_raise():
    prod._producer = None

    prod.on_close(None, 1000, "closed")


def test_on_open_and_on_error_do_not_raise():
    prod.on_open(None)
    prod.on_error(None, RuntimeError("oops"))


def test_main_builds_websocket_and_flushes_on_interrupt(monkeypatch):
    created = {}

    class FakeWS:
        def __init__(self, url, on_open, on_message, on_error, on_close):
            created["url"] = url
            created["handlers"] = (on_open, on_message, on_error, on_close)

        def run_forever(self):
            raise KeyboardInterrupt()

    prod._producer = MagicMock()
    monkeypatch.setattr(prod, "_build_producer", lambda: (prod._producer, MagicMock()))
    monkeypatch.setattr(prod.websocket, "WebSocketApp", FakeWS)

    prod.main()

    assert created["url"] == prod.BINANCE_WS_URL
    prod._producer.flush.assert_called_once()


def test_main_does_not_flush_when_producer_missing(monkeypatch):
    created = {}

    class FakeWS:
        def __init__(self, url, on_open, on_message, on_error, on_close):
            created["url"] = url

        def run_forever(self):
            raise KeyboardInterrupt()

    monkeypatch.setattr(prod, "_build_producer", lambda: (None, MagicMock()))
    monkeypatch.setattr(prod.websocket, "WebSocketApp", FakeWS)

    prod.main()

    assert created["url"] == prod.BINANCE_WS_URL
