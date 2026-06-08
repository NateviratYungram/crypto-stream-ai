"""
Unit tests for streaming/lake_writer.py.

Covers flush_to_parquet output shape/types and _deserialize fault tolerance.
No Kafka broker or Schema Registry required.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pyarrow.parquet as pq
import pytest

import lake_writer as lw


def _time_sequence(*values: float):
    remaining = iter(values)
    last = values[-1] if values else 0.0

    def _fake_time():
        nonlocal last
        try:
            last = next(remaining)
        except StopIteration:
            pass
        return last

    return _fake_time


_SAMPLE_RECORDS = [
    {
        "trade_id":       "111",
        "symbol":         "BTCUSDT",
        "price":          "67500.12",
        "quantity":       "0.015",
        "timestamp":      1700000000000,
        "is_buyer_maker": False,
        "ingested_at":    "2024-11-14T22:13:20.000Z",
    },
    {
        "trade_id":       "222",
        "symbol":         "ETHUSDT",
        "price":          "3500.00",
        "quantity":       "0.5",
        "timestamp":      1700000001000,
        "is_buyer_maker": True,
        "ingested_at":    "2024-11-14T22:13:21.000Z",
    },
]


# ── flush_to_parquet ──────────────────────────────────────────────────────────

@pytest.fixture
def tmp_lake(tmp_path, monkeypatch):
    monkeypatch.setattr(lw, "DATALAKE_BASE_PATH", str(tmp_path))
    return tmp_path


def _read_parquet(tmp_lake) -> "pd.DataFrame":
    import pandas as pd
    files = list(tmp_lake.rglob("*.parquet"))
    assert files, "No Parquet file was written"
    return pq.read_table(files[0]).to_pandas()


def test_flush_creates_parquet_file(tmp_lake):
    lw.flush_to_parquet(_SAMPLE_RECORDS, datetime.now(timezone.utc))
    files = list(tmp_lake.rglob("*.parquet"))
    assert len(files) == 1


def test_flush_hive_partition_path(tmp_lake):
    dt = datetime(2024, 11, 14, tzinfo=timezone.utc)
    lw.flush_to_parquet(_SAMPLE_RECORDS, dt)
    files = list(tmp_lake.rglob("*.parquet"))
    path_str = str(files[0])
    assert "year=2024" in path_str
    assert "month=11" in path_str
    assert "day=14" in path_str


def test_flush_row_count(tmp_lake):
    lw.flush_to_parquet(_SAMPLE_RECORDS, datetime.now(timezone.utc))
    df = _read_parquet(tmp_lake)
    assert len(df) == len(_SAMPLE_RECORDS)


def test_flush_column_names(tmp_lake):
    lw.flush_to_parquet(_SAMPLE_RECORDS, datetime.now(timezone.utc))
    df = _read_parquet(tmp_lake)
    expected = {"trade_id", "symbol", "price", "quantity", "timestamp", "is_buyer_maker", "ingested_at"}
    # PyArrow may append partition columns (year/month/day) when reading Hive paths
    assert expected.issubset(set(df.columns))


def test_flush_price_is_float(tmp_lake):
    lw.flush_to_parquet(_SAMPLE_RECORDS, datetime.now(timezone.utc))
    df = _read_parquet(tmp_lake)
    assert df["price"].dtype.kind == "f"


def test_flush_noop_on_empty_records(tmp_lake):
    lw.flush_to_parquet([], datetime.now(timezone.utc))
    files = list(tmp_lake.rglob("*.parquet"))
    assert len(files) == 0


def test_flush_adds_missing_schema_columns(tmp_lake):
    incomplete = [
        {
            "trade_id": "333",
            "symbol": "SOLUSDT",
            "price": "150.5",
            "quantity": "1.25",
            "timestamp": 1700000002000,
            "is_buyer_maker": False,
        }
    ]

    lw.flush_to_parquet(incomplete, datetime.now(timezone.utc))
    df = _read_parquet(tmp_lake)

    assert "ingested_at" in df.columns
    assert df["ingested_at"].isna().all()


# ── _deserialize ─────────────────────────────────────────────────────────────

def test_deserialize_returns_dict_on_success():
    deserializer = MagicMock(return_value={"trade_id": "1", "symbol": "BTCUSDT"})
    msg = MagicMock()
    msg.value.return_value = b"avro-bytes"
    result = lw._deserialize(msg, deserializer)
    assert isinstance(result, dict)
    assert result["symbol"] == "BTCUSDT"


def test_deserialize_returns_none_on_error():
    deserializer = MagicMock(side_effect=Exception("bad schema"))
    msg = MagicMock()
    msg.value.return_value = b"garbage"
    result = lw._deserialize(msg, deserializer)
    assert result is None


def test_partition_helpers():
    dt = datetime(2026, 5, 25, 10, 11, 12, 123456, tzinfo=timezone.utc)
    path = lw._partition_path(dt)
    filename = lw._output_filename(dt)

    assert "year=2026" in path
    assert "month=05" in path
    assert "day=25" in path
    assert filename.startswith("trades_20260525_101112_123456")


def test_should_flush_checks_record_and_time_limits(monkeypatch):
    monkeypatch.setattr(lw, "FLUSH_RECORD_LIMIT", 3)
    monkeypatch.setattr(lw, "FLUSH_TIME_LIMIT", 10)

    assert lw._should_flush([1, 2, 3], 0.0, 1.0) == (True, "record_limit")
    assert lw._should_flush([1], 0.0, 15.0) == (True, "time_limit")
    assert lw._should_flush([1], 5.0, 10.0) == (False, None)


def test_handle_message_appends_only_deserialized_records():
    buffer = []
    deserializer = MagicMock(return_value={"trade_id": "1"})
    msg = MagicMock()
    msg.value.return_value = b"x"

    assert lw._handle_message(msg, deserializer, buffer) is True
    assert buffer == [{"trade_id": "1"}]

    bad = MagicMock(side_effect=Exception("bad"))
    assert lw._handle_message(msg, bad, buffer) is False
    assert buffer == [{"trade_id": "1"}]


def test_build_consumer_uses_config(monkeypatch):
    created = {}

    class FakeRegistryClient:
        def __init__(self, config):
            created["registry"] = config

    class FakeDeserializer:
        def __init__(self, registry):
            created["deserializer_registry"] = registry

    class FakeConsumer:
        def __init__(self, config):
            created["consumer"] = config

    monkeypatch.setattr(lw, "SchemaRegistryClient", FakeRegistryClient)
    monkeypatch.setattr(lw, "AvroDeserializer", FakeDeserializer)
    monkeypatch.setattr(lw, "Consumer", FakeConsumer)

    consumer, deserializer = lw._build_consumer()

    assert isinstance(consumer, FakeConsumer)
    assert isinstance(deserializer, FakeDeserializer)
    assert created["registry"]["url"] == lw.SCHEMA_REGISTRY_URL
    assert created["consumer"]["bootstrap.servers"] == lw.KAFKA_BROKER


def test_main_flushes_on_idle_and_shutdown(monkeypatch, tmp_path):
    monkeypatch.setattr(lw, "DATALAKE_BASE_PATH", str(tmp_path))
    monkeypatch.setattr(lw, "FLUSH_RECORD_LIMIT", 5)
    monkeypatch.setattr(lw, "FLUSH_TIME_LIMIT", 10)

    class FakeMessage:
        def __init__(self, payload=None, error=None):
            self._payload = payload
            self._error = error

        def value(self):
            return self._payload

        def error(self):
            return self._error

    class FakeConsumer:
        def __init__(self, messages):
            self.messages = list(messages)
            self.closed = False
            self.subscribed = None

        def subscribe(self, topics):
            self.subscribed = topics

        def poll(self, timeout=1.0):
            item = self.messages.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        def close(self):
            self.closed = True

    consumer = FakeConsumer([FakeMessage(payload=b"1"), None, KeyboardInterrupt()])
    monkeypatch.setattr(lw, "_build_consumer", lambda: (consumer, MagicMock()))
    monkeypatch.setattr(lw, "_deserialize", lambda msg, deserializer: {"trade_id": "1", "symbol": "BTC", "price": "1", "quantity": "2", "timestamp": 1, "is_buyer_maker": False, "ingested_at": "now"})

    monkeypatch.setattr(lw.time, "time", _time_sequence(0.0, 11.0, 11.0, 12.0, 12.0))
    flushes = []
    monkeypatch.setattr(lw, "flush_to_parquet", lambda records, flush_time: flushes.append((list(records), flush_time)))

    lw.main()

    assert consumer.subscribed == [lw.KAFKA_TOPIC]
    assert consumer.closed is True
    assert len(flushes) == 1
    assert flushes[0][0][0]["trade_id"] == "1"


def test_main_idle_flushes_buffer_when_time_limit_hits(monkeypatch, tmp_path):
    monkeypatch.setattr(lw, "DATALAKE_BASE_PATH", str(tmp_path))
    monkeypatch.setattr(lw, "FLUSH_RECORD_LIMIT", 5)
    monkeypatch.setattr(lw, "FLUSH_TIME_LIMIT", 10)

    class FakeMessage:
        def __init__(self, payload=None):
            self._payload = payload

        def value(self):
            return self._payload

        def error(self):
            return None

    class FakeConsumer:
        def __init__(self, messages):
            self.messages = list(messages)
            self.closed = False

        def subscribe(self, topics):
            self.topics = topics

        def poll(self, timeout=1.0):
            item = self.messages.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        def close(self):
            self.closed = True

    consumer = FakeConsumer([FakeMessage(payload=b"1"), None, KeyboardInterrupt()])
    monkeypatch.setattr(lw, "_build_consumer", lambda: (consumer, MagicMock()))
    monkeypatch.setattr(
        lw,
        "_deserialize",
        lambda msg, deserializer: {
            "trade_id": "1",
            "symbol": "BTC",
            "price": "1",
            "quantity": "2",
            "timestamp": 1,
            "is_buyer_maker": False,
            "ingested_at": "now",
        },
    )
    monkeypatch.setattr(lw.time, "time", _time_sequence(0.0, 1.0, 11.0, 12.0))
    flushes = []
    monkeypatch.setattr(lw, "flush_to_parquet", lambda records, flush_time: flushes.append((list(records), flush_time)))

    lw.main()

    assert len(flushes) == 1
    assert flushes[0][0][0]["trade_id"] == "1"
    assert consumer.closed is True


def test_main_handles_partition_eof_and_other_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(lw, "DATALAKE_BASE_PATH", str(tmp_path))

    class FakeErr:
        def __init__(self, code):
            self._code = code

        def code(self):
            return self._code

    class FakeMessage:
        def __init__(self, err=None):
            self._err = err

        def error(self):
            return self._err

    class FakeConsumer:
        def __init__(self, messages):
            self.messages = list(messages)
            self.closed = False

        def subscribe(self, topics):
            self.topics = topics

        def poll(self, timeout=1.0):
            item = self.messages.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        def close(self):
            self.closed = True

    monkeypatch.setattr(lw.KafkaError, "_PARTITION_EOF", "EOF")
    consumer = FakeConsumer([FakeMessage(err=FakeErr("EOF")), FakeMessage(err=FakeErr("BAD"))])
    monkeypatch.setattr(lw, "_build_consumer", lambda: (consumer, MagicMock()))
    monkeypatch.setattr(lw.time, "time", lambda: 0.0)

    with pytest.raises(Exception):
        lw.main()

    assert consumer.closed is True


def test_main_skips_flush_when_idle_without_buffer(monkeypatch, tmp_path):
    monkeypatch.setattr(lw, "DATALAKE_BASE_PATH", str(tmp_path))

    class FakeConsumer:
        def __init__(self):
            self.closed = False
            self.calls = 0

        def subscribe(self, topics):
            self.topics = topics

        def poll(self, timeout=1.0):
            self.calls += 1
            if self.calls == 1:
                return None
            raise KeyboardInterrupt()

        def close(self):
            self.closed = True

    consumer = FakeConsumer()
    monkeypatch.setattr(lw, "_build_consumer", lambda: (consumer, MagicMock()))
    monkeypatch.setattr(lw.time, "time", lambda: 0.0)
    flushes = []
    monkeypatch.setattr(lw, "flush_to_parquet", lambda records, flush_time: flushes.append((records, flush_time)))

    lw.main()

    assert flushes == []
    assert consumer.closed is True


def test_main_continues_when_deserialize_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(lw, "DATALAKE_BASE_PATH", str(tmp_path))
    monkeypatch.setattr(lw, "FLUSH_RECORD_LIMIT", 5)
    monkeypatch.setattr(lw, "FLUSH_TIME_LIMIT", 10)

    class FakeMessage:
        def error(self):
            return None

    class FakeConsumer:
        def __init__(self):
            self.closed = False
            self.calls = 0

        def subscribe(self, topics):
            self.topics = topics

        def poll(self, timeout=1.0):
            self.calls += 1
            if self.calls == 1:
                return FakeMessage()
            raise KeyboardInterrupt()

        def close(self):
            self.closed = True

    consumer = FakeConsumer()
    monkeypatch.setattr(lw, "_build_consumer", lambda: (consumer, MagicMock()))
    monkeypatch.setattr(lw, "_handle_message", lambda msg, deserializer, buffer: False)
    monkeypatch.setattr(lw.time, "time", lambda: 0.0)
    flushes = []
    monkeypatch.setattr(lw, "flush_to_parquet", lambda records, flush_time: flushes.append((records, flush_time)))

    lw.main()

    assert flushes == []
    assert consumer.closed is True


def test_main_flushes_on_record_limit_after_successful_message(monkeypatch, tmp_path):
    monkeypatch.setattr(lw, "DATALAKE_BASE_PATH", str(tmp_path))
    monkeypatch.setattr(lw, "FLUSH_RECORD_LIMIT", 1)
    monkeypatch.setattr(lw, "FLUSH_TIME_LIMIT", 30)

    class FakeMessage:
        def value(self):
            return b"payload"

        def error(self):
            return None

    class FakeConsumer:
        def __init__(self):
            self.closed = False
            self.calls = 0

        def subscribe(self, topics):
            self.topics = topics

        def poll(self, timeout=1.0):
            self.calls += 1
            if self.calls == 1:
                return FakeMessage()
            raise KeyboardInterrupt()

        def close(self):
            self.closed = True

    consumer = FakeConsumer()
    monkeypatch.setattr(lw, "_build_consumer", lambda: (consumer, MagicMock()))
    monkeypatch.setattr(
        lw,
        "_deserialize",
        lambda msg, deserializer: {
            "trade_id": "1",
            "symbol": "BTC",
            "price": "1",
            "quantity": "2",
            "timestamp": 1,
            "is_buyer_maker": False,
            "ingested_at": "now",
        },
    )
    monkeypatch.setattr(lw.time, "time", _time_sequence(0.0, 1.0, 2.0))
    flushes = []
    monkeypatch.setattr(lw, "flush_to_parquet", lambda records, flush_time: flushes.append((list(records), flush_time)))

    lw.main()

    assert len(flushes) == 1
    assert flushes[0][0][0]["trade_id"] == "1"
    assert consumer.closed is True


def test_main_flushes_remaining_buffer_on_keyboard_interrupt(monkeypatch, tmp_path):
    monkeypatch.setattr(lw, "DATALAKE_BASE_PATH", str(tmp_path))
    monkeypatch.setattr(lw, "FLUSH_RECORD_LIMIT", 5)
    monkeypatch.setattr(lw, "FLUSH_TIME_LIMIT", 30)

    class FakeMessage:
        def value(self):
            return b"payload"

        def error(self):
            return None

    class FakeConsumer:
        def __init__(self):
            self.closed = False
            self.calls = 0

        def subscribe(self, topics):
            self.topics = topics

        def poll(self, timeout=1.0):
            self.calls += 1
            if self.calls == 1:
                return FakeMessage()
            raise KeyboardInterrupt()

        def close(self):
            self.closed = True

    consumer = FakeConsumer()
    monkeypatch.setattr(lw, "_build_consumer", lambda: (consumer, MagicMock()))
    monkeypatch.setattr(
        lw,
        "_deserialize",
        lambda msg, deserializer: {
            "trade_id": "99",
            "symbol": "ETH",
            "price": "2",
            "quantity": "3",
            "timestamp": 2,
            "is_buyer_maker": True,
            "ingested_at": "later",
        },
    )
    monkeypatch.setattr(lw.time, "time", lambda: 0.0)
    flushes = []
    monkeypatch.setattr(lw, "flush_to_parquet", lambda records, flush_time: flushes.append((list(records), flush_time)))

    lw.main()

    assert len(flushes) == 1
    assert flushes[0][0][0]["trade_id"] == "99"
    assert consumer.closed is True
