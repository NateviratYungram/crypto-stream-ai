"""
Unit tests for Kafka producer (streaming/producer.py).

Tests Binance WebSocket message parsing and Avro record construction.
No Kafka broker, Schema Registry, or network connection required —
_producer and _avro_serializer are replaced with lightweight stubs.
"""
import json
import re
from unittest.mock import MagicMock

import pytest

import producer as prod

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


def test_price_is_string():
    """Avro decimal fields are encoded as strings to preserve precision."""
    record = _capture_record()
    assert isinstance(record["price"], str)


def test_quantity_is_string():
    record = _capture_record()
    assert isinstance(record["quantity"], str)


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
