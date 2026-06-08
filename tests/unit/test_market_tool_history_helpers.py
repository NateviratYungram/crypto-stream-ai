from datetime import datetime, timedelta

from intelligence.tools.market_tool_history_helpers import (
    _build_historical_ranking_insert_payload,
    _build_live_historical_rankings_response,
    _build_persisted_historical_rankings_response,
    _historical_rankings_are_fresh,
    _serialize_historical_ranking_rows,
)


def test_build_historical_ranking_insert_payload_maps_rows():
    payload = _build_historical_ranking_insert_payload(
        [
            {
                "symbol": "AAPL",
                "yf_symbol": "AAPL",
                "start_date": "2014-01-01",
                "end_date": "2024-01-01",
                "start_price": 10.0,
                "end_price": 20.0,
                "total_return_pct": 100.0,
                "cagr_pct": 7.2,
                "max_drawdown_pct": -25.5,
            }
        ],
        years=10,
        universe="SP500",
        full_window_only=True,
    )

    assert payload == [
        (
            "AAPL",
            "AAPL",
            "SP500",
            10,
            True,
            "2024-01-01",
            "2014-01-01",
            "2024-01-01",
            10.0,
            20.0,
            100.0,
            7.2,
            -25.5,
            "yfinance",
        )
    ]


def test_historical_rankings_are_fresh_checks_counts_and_age():
    now = datetime(2026, 5, 26, 12, 0, 0)

    assert not _historical_rankings_are_fresh({}, max_age_hours=24, now=now)
    assert not _historical_rankings_are_fresh(
        {"eligible_count": 5, "updated_at": None},
        max_age_hours=24,
        now=now,
    )
    assert not _historical_rankings_are_fresh(
        {"eligible_count": 5, "updated_at": now - timedelta(hours=30)},
        max_age_hours=24,
        now=now,
    )
    assert _historical_rankings_are_fresh(
        {"eligible_count": 5, "updated_at": now - timedelta(hours=2)},
        max_age_hours=24,
        now=now,
    )


def test_serialize_historical_ranking_rows_normalizes_dates_and_numbers():
    rows = _serialize_historical_ranking_rows(
        [
            {
                "symbol": "MSFT",
                "start_date": datetime(2020, 1, 1),
                "end_date": datetime(2024, 1, 1),
                "start_price": 100.123,
                "end_price": 200.987,
                "total_return_pct": 100.444,
                "cagr_pct": 18.899,
                "max_drawdown_pct": -33.333,
            }
        ]
    )

    assert rows[0]["start_date"].startswith("2020-01-01")
    assert rows[0]["end_date"].startswith("2024-01-01")
    assert rows[0]["start_price"] == 100.12
    assert rows[0]["end_price"] == 200.99
    assert rows[0]["total_return_pct"] == 100.44
    assert rows[0]["cagr_pct"] == 18.9
    assert rows[0]["max_drawdown_pct"] == -33.33


def test_build_persisted_historical_rankings_response_formats_meta():
    updated_at = datetime(2026, 5, 26, 9, 30, 0)
    response = _build_persisted_historical_rankings_response(
        meta={
            "eligible_count": 22,
            "as_of_date": datetime(2026, 5, 25),
            "updated_at": updated_at,
        },
        rows=[{"symbol": "NVDA", "total_return_pct": 450.126}],
        years=10,
        direction="top",
        universe="NASDAQ100",
        full_window_only=False,
    )

    assert response["status"] == "SUCCESS"
    assert response["eligible_count"] == 22
    assert response["as_of"].startswith("2026-05-25")
    assert response["updated_at"].startswith("2026-05-26T09:30:00")
    assert response["results"][0]["total_return_pct"] == 450.13


def test_build_live_historical_rankings_response_applies_limit():
    rankings = [{"symbol": "A"}, {"symbol": "B"}, {"symbol": "C"}]

    response = _build_live_historical_rankings_response(
        rankings=rankings,
        years=5,
        direction="bottom",
        universe="COMBINED",
        full_window_only=True,
        as_of="2026-05-26",
        eligible_count=40,
        excluded_count=2,
        limit=2,
    )

    assert response["results"] == [{"symbol": "A"}, {"symbol": "B"}]
    assert response["source"] == "live_compute"
