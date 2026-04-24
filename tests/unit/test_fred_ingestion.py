"""
Unit tests for FRED CSV parsing in fred_ingestion_dag.py.

Tests run without network access, Airflow, or PostgreSQL. The requests
library is patched so _fetch_series() can be exercised against controlled
CSV payloads — including FRED's quirks like '.' for missing values.
"""
from unittest.mock import MagicMock, patch

import pytest

from fred_ingestion_dag import _fetch_series


def _mock_response(csv_body: str) -> MagicMock:
    mock = MagicMock()
    mock.text = csv_body
    mock.raise_for_status = MagicMock()
    return mock


# ── Happy path ───────────────────────────────────────────────────────────────

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


# ── FRED-specific edge cases ─────────────────────────────────────────────────

def test_skips_missing_value_dot():
    """FRED uses '.' for observations not yet released — must be silently dropped."""
    csv = "DATE,VALUE\n2024-01-01,5.33\n2024-01-02,.\n2024-01-03,5.34\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    assert len(rows) == 2
    dates = [r["date"] for r in rows]
    assert "2024-01-02" not in dates


def test_skips_empty_value_field():
    """A trailing comma with no value should also be dropped."""
    csv = "DATE,VALUE\n2024-01-01,5.33\n2024-01-02,\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    assert len(rows) == 1


def test_skips_malformed_lines():
    """Lines with more or fewer than 2 comma-separated fields are dropped."""
    csv = "DATE,VALUE\n2024-01-01,5.33\nbad-line\n2024-01-03,5.34\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    assert len(rows) == 2


def test_skips_non_numeric_values():
    """Non-parseable numeric strings are silently dropped."""
    csv = "DATE,VALUE\n2024-01-01,5.33\n2024-01-02,N/A\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    assert len(rows) == 1


def test_returns_empty_list_for_header_only():
    """A response with only the header row should return []."""
    csv = "DATE,VALUE\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    assert rows == []


def test_header_row_not_included_in_output():
    """The 'DATE,VALUE' header line must never appear as a data row."""
    csv = "DATE,VALUE\n2024-01-01,5.33\n"
    with patch("fred_ingestion_dag.requests") as mock_req:
        mock_req.get.return_value = _mock_response(csv)
        rows = _fetch_series("DFF")

    for row in rows:
        assert row["date"] != "DATE"
