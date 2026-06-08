"""
Unit tests for fred_ingestion_dag.py helpers and task functions.

These tests run without network access, Airflow, or PostgreSQL by patching
requests, psycopg2, and the task-level collaborators.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

import fred_ingestion_dag as fred_module
from fred_ingestion_dag import (
    _ensure_table,
    _fetch_series,
    _get_conn,
    _upsert_rows,
    ingest_fred_series,
    validate_fred_data,
)


def _mock_response(csv_body: str) -> MagicMock:
    mock = MagicMock()
    mock.text = csv_body
    mock.raise_for_status = MagicMock()
    return mock


def test_parses_valid_rows():
    csv = "DATE,VALUE\n2024-01-01,5.33\n2024-01-02,5.34\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    assert len(rows) == 2
    assert rows[0] == {"date": "2024-01-01", "value": 5.33}
    assert rows[1] == {"date": "2024-01-02", "value": 5.34}


def test_values_are_floats():
    csv = "DATE,VALUE\n2024-01-01,5.33\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    assert isinstance(rows[0]["value"], float)


def test_dates_are_strings():
    csv = "DATE,VALUE\n2024-01-01,5.33\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    assert isinstance(rows[0]["date"], str)


def test_skips_missing_value_dot():
    csv = "DATE,VALUE\n2024-01-01,5.33\n2024-01-02,.\n2024-01-03,5.34\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    assert len(rows) == 2
    assert [row["date"] for row in rows] == ["2024-01-01", "2024-01-03"]


def test_skips_empty_value_field():
    csv = "DATE,VALUE\n2024-01-01,5.33\n2024-01-02,\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    assert len(rows) == 1


def test_skips_malformed_lines():
    csv = "DATE,VALUE\n2024-01-01,5.33\nbad-line\n2024-01-03,5.34\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    assert len(rows) == 2


def test_skips_non_numeric_values():
    csv = "DATE,VALUE\n2024-01-01,5.33\n2024-01-02,N/A\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    assert len(rows) == 1


def test_returns_empty_list_for_header_only():
    csv = "DATE,VALUE\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    assert rows == []


def test_header_row_not_included_in_output():
    csv = "DATE,VALUE\n2024-01-01,5.33\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    for row in rows:
        assert row["date"] != "DATE"


class DummyCursor:
    def __init__(self, fetchone_result=None):
        self.fetchone_result = fetchone_result
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql):
        self.executed.append(sql)

    def fetchone(self):
        return self.fetchone_result


class DummyConn:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.commits = 0
        self.closed = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed += 1


def test_get_conn_uses_db_config(monkeypatch):
    recorded = {}

    def fake_connect(**kwargs):
        recorded["kwargs"] = kwargs
        return "conn"

    monkeypatch.setattr(fred_module.psycopg2, "connect", fake_connect)

    result = _get_conn()

    assert result == "conn"
    assert recorded["kwargs"] == fred_module.DB_CONFIG


def test_ensure_table_creates_table_and_index():
    cursor = DummyCursor()
    conn = DummyConn(cursor)

    _ensure_table(conn)

    assert len(cursor.executed) == 2
    assert "CREATE TABLE IF NOT EXISTS macro_indicators" in cursor.executed[0]
    assert "CREATE INDEX IF NOT EXISTS idx_macro_indicators_date" in cursor.executed[1]
    assert conn.commits == 1


def test_upsert_rows_returns_zero_without_rows():
    conn = DummyConn(DummyCursor())

    assert _upsert_rows(conn, "DFF", "Fed Funds", "daily", []) == 0
    assert conn.commits == 0


def test_upsert_rows_executes_bulk_insert_and_commits(monkeypatch):
    cursor = DummyCursor()
    conn = DummyConn(cursor)
    captured = {}

    def fake_execute_values(cur, sql, tuples, page_size):
        captured["cursor"] = cur
        captured["sql"] = sql
        captured["tuples"] = tuples
        captured["page_size"] = page_size

    monkeypatch.setattr(fred_module.psycopg2.extras, "execute_values", fake_execute_values)

    rows = [{"date": "2024-01-01", "value": 5.25}, {"date": "2024-01-02", "value": 5.3}]
    inserted = _upsert_rows(conn, "DFF", "Fed Funds", "daily", rows)

    assert inserted == 2
    assert captured["cursor"] is cursor
    assert "INSERT INTO macro_indicators" in captured["sql"]
    assert captured["tuples"] == [
        ("DFF", "Fed Funds", "2024-01-01", 5.25, "daily"),
        ("DFF", "Fed Funds", "2024-01-02", 5.3, "daily"),
    ]
    assert captured["page_size"] == 500
    assert conn.commits == 1


def test_ingest_fred_series_pushes_total_rows(monkeypatch):
    conn = DummyConn(DummyCursor())
    side_effects = []

    monkeypatch.setattr(fred_module, "_get_conn", lambda: conn)
    monkeypatch.setattr(fred_module, "_ensure_table", lambda current_conn: side_effects.append(("ensure", current_conn)))
    monkeypatch.setattr(fred_module, "_fetch_series", lambda series_id, lookback_days=400: [{"date": "2024-01-01", "value": 1.0}])
    monkeypatch.setattr(fred_module, "_upsert_rows", lambda current_conn, series_id, series_name, frequency, rows: len(rows))

    ti = MagicMock()
    ingest_fred_series(ti=ti)

    assert side_effects == [("ensure", conn)]
    assert conn.closed == 1
    ti.xcom_push.assert_called_once_with(key="total_rows", value=len(fred_module.FRED_SERIES))


def test_ingest_fred_series_raises_partial_failure_after_processing(monkeypatch):
    conn = DummyConn(DummyCursor())

    monkeypatch.setattr(fred_module, "_get_conn", lambda: conn)
    monkeypatch.setattr(fred_module, "_ensure_table", lambda current_conn: None)

    def fake_fetch(series_id, lookback_days=400):
        if series_id == "T10Y2Y":
            raise RuntimeError("network down")
        return [{"date": "2024-01-01", "value": 1.0}]

    monkeypatch.setattr(fred_module, "_fetch_series", fake_fetch)
    monkeypatch.setattr(fred_module, "_upsert_rows", lambda current_conn, series_id, series_name, frequency, rows: len(rows))

    with pytest.raises(RuntimeError, match="T10Y2Y: network down"):
        ingest_fred_series(ti=MagicMock())

    assert conn.closed == 1


def test_validate_fred_data_warns_when_data_is_stale(monkeypatch):
    cursor = DummyCursor(fetchone_result=(date(2024, 1, 1), 42))
    conn = DummyConn(cursor)
    warned = []

    class FakeDateTime:
        @staticmethod
        def now(tz=None):
            from datetime import datetime
            return datetime(2024, 1, 10, tzinfo=tz)

    monkeypatch.setattr(fred_module, "_get_conn", lambda: conn)
    monkeypatch.setattr(fred_module, "datetime", FakeDateTime)
    monkeypatch.setattr(fred_module.log, "warning", lambda message, latest, expected: warned.append((message, latest, expected)))

    validate_fred_data()

    assert cursor.executed
    assert conn.closed == 1
    assert len(warned) == 1
    assert warned[0][1:] == (date(2024, 1, 1), date(2024, 1, 7))
    assert "latest: %s" in warned[0][0]


def test_validate_fred_data_skips_warning_for_missing_or_fresh_data(monkeypatch):
    missing_conn = DummyConn(DummyCursor(fetchone_result=(None, 0)))
    fresh_conn = DummyConn(DummyCursor(fetchone_result=(date(2024, 1, 9), 10)))
    warned = []

    class FakeDateTime:
        @staticmethod
        def now(tz=None):
            from datetime import datetime
            return datetime(2024, 1, 10, tzinfo=tz)

    connections = [missing_conn, fresh_conn]
    monkeypatch.setattr(fred_module, "_get_conn", lambda: connections.pop(0))
    monkeypatch.setattr(fred_module, "datetime", FakeDateTime)
    monkeypatch.setattr(fred_module.log, "warning", lambda *args: warned.append(args))

    validate_fred_data()
    validate_fred_data()

    assert warned == []
    assert missing_conn.closed == 1
    assert fresh_conn.closed == 1
