from datetime import datetime, timedelta

import pandas as pd

from intelligence.tools.market_tool_index_helpers import (
    _build_index_summary_response,
    _normalize_index_requests,
    _summarize_index_close_series,
)


def test_normalize_index_requests_maps_aliases_and_deduplicates():
    result = _normalize_index_requests(
        ["ndx", "NASDAQ_100", "gspc", "unknown"],
        alias_map={
            "NDX": "NASDAQ_100",
            "NASDAQ_100": "NASDAQ_100",
            "GSPC": "SP500",
        },
        ticker_map={"NASDAQ_100": "^NDX", "SP500": "^GSPC"},
        fallback=["NASDAQ_100", "SP500"],
    )

    assert result == ["NASDAQ_100", "SP500"]


def test_normalize_index_requests_uses_fallback_when_empty():
    result = _normalize_index_requests(
        [],
        alias_map={},
        ticker_map={"NASDAQ_100": "^NDX"},
        fallback=["NASDAQ_100"],
    )

    assert result == ["NASDAQ_100"]


def test_summarize_index_close_series_returns_none_for_short_series():
    short = pd.Series(
        [100.0, 101.0],
        index=pd.date_range("2024-01-01", periods=2, freq="D"),
    )

    assert _summarize_index_close_series(short, label="NASDAQ 100", ticker="^NDX") is None


def test_summarize_index_close_series_builds_metrics():
    index = pd.date_range("2023-01-01", periods=260, freq="D")
    close = pd.Series([100 + i * 0.5 for i in range(260)], index=index)

    result = _summarize_index_close_series(close, label="NASDAQ 100", ticker="^NDX")

    assert result["label"] == "NASDAQ 100"
    assert result["ticker"] == "^NDX"
    assert result["start_date"] == "2023-01-01"
    assert result["end_price"] > result["start_price"]
    assert result["trend"] == "bullish"
    assert result["one_year_return_pct"] is not None


def test_build_index_summary_response_orders_ranking():
    response = _build_index_summary_response(
        years=5,
        summaries={
            "SP500": {"label": "S&P 500", "trend": "mixed"},
            "NASDAQ_100": {"label": "NASDAQ 100", "trend": "bullish"},
        },
        ranking=[("SP500", 0.2), ("NASDAQ_100", 0.4)],
    )

    assert response["status"] == "SUCCESS"
    assert response["best_index"] == "NASDAQ_100"
    assert response["worst_index"] == "SP500"
    assert response["ranking"][0]["index"] == "NASDAQ_100"
    assert response["ranking"][0]["total_return_pct"] == 40.0
