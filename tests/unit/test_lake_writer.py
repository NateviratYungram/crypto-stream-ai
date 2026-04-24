"""
Unit tests for streaming/lake_writer.py.

Covers flush_to_parquet output shape/types and _deserialize fault tolerance.
No Kafka broker or Schema Registry required.
"""
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pyarrow.parquet as pq
import pytest

import lake_writer as lw

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
