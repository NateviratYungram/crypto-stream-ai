from datetime import datetime, timedelta, timezone

import pytest

from intelligence.ml.anomaly_detection import (
    OhlcvPoint,
    _as_datetime,
    _as_float,
    _severity,
    _zscore,
    classify_asset_class,
    detect_market_anomalies,
    is_continuous_market_symbol,
    normalize_ohlcv_rows,
    threshold_profile,
)


def _row(ts, close=100.0, volume=100.0, high=None, low=None):
    high = high if high is not None else close * 1.01
    low = low if low is not None else close * 0.99
    return {
        "symbol": "BTC-USD",
        "timeframe": "1m",
        "ts": ts,
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def test_detects_absolute_price_return_spike_when_baseline_is_flat():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [_row(start + timedelta(minutes=i), close=100.0) for i in range(14)]
    rows.append(_row(start + timedelta(minutes=14), close=112.0))

    events = detect_market_anomalies(rows, min_baseline=12)

    assert any(event["anomaly_type"] == "price_return_spike" for event in events)


def test_detects_volume_spike_by_ratio_when_stddev_is_zero():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [_row(start + timedelta(minutes=i), volume=100.0) for i in range(14)]
    rows.append(_row(start + timedelta(minutes=14), volume=800.0))

    events = detect_market_anomalies(rows, min_baseline=12)

    volume_events = [event for event in events if event["anomaly_type"] == "volume_spike"]
    assert len(volume_events) == 1
    assert volume_events[0]["details"]["volume_ratio"] == 8.0


def test_detects_missing_candle_gap():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        _row(start),
        _row(start + timedelta(minutes=1)),
        _row(start + timedelta(minutes=8)),
    ]

    events = detect_market_anomalies(rows)

    gap_events = [event for event in events if event["anomaly_type"] == "missing_candle_gap"]
    assert len(gap_events) == 1
    assert gap_events[0]["details"]["estimated_missing_candles"] == 6


def test_skips_missing_gap_for_session_based_symbol():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        {**_row(start), "symbol": "^DJI"},
        {**_row(start + timedelta(hours=18)), "symbol": "^DJI"},
    ]

    events = detect_market_anomalies(rows)

    assert not [event for event in events if event["anomaly_type"] == "missing_candle_gap"]


def test_helper_functions_cover_fallbacks_and_asset_profiles():
    assert _as_float(None, default=1.5) == 1.5
    assert _as_float("bad", default=2.5) == 2.5
    assert _as_datetime("2026-01-01T00:00:00Z").tzinfo is not None
    with pytest.raises(TypeError):
        _as_datetime(123)

    assert _zscore(5.0, [1.0, 1.0, 1.0, 1.0]) == 0.0
    assert _zscore(5.0, [1.0, 2.0, 3.0, 4.0, 5.0]) >= 0.0
    assert _severity(2.9) == "LOW"
    assert _severity(3.2) == "MEDIUM"
    assert _severity(4.5) == "HIGH"
    assert _severity(6.5) == "CRITICAL"
    assert is_continuous_market_symbol("BTCUSD") is True
    assert is_continuous_market_symbol("^DJI") is False
    assert classify_asset_class("EURUSD") == "FOREX"
    assert classify_asset_class("ES=F") == "FUTURES"
    assert classify_asset_class("UNKNOWN") == "DEFAULT"
    assert threshold_profile("EURUSD")["gap_multiplier"] == 999.0


def test_normalize_rows_sorts_and_detects_range_spike_without_volume():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        {
            "symbol": "ethusd",
            "timeframe": "1m",
            "ts": (start + timedelta(minutes=1)).isoformat(),
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
        },
        {
            "symbol": "ethusd",
            "timeframe": "1m",
            "ts": start.isoformat(),
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
        },
    ]
    normalized = normalize_ohlcv_rows(rows)

    assert normalized[0].symbol == "ETHUSD"
    assert normalized[0].ts < normalized[1].ts
    assert normalized[0].volume is None

    padded = [_row(start + timedelta(minutes=i), high=101.0, low=99.0, volume=None) for i in range(14)]
    padded.append(_row(start + timedelta(minutes=14), high=150.0, low=50.0, volume=0))
    events = detect_market_anomalies(padded, min_baseline=12)

    assert any(event["anomaly_type"] == "candle_range_spike" for event in events)
    assert not any(event["anomaly_type"] == "volume_spike" for event in events)


def test_detect_market_anomalies_accepts_points_and_empty_rows():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    point_rows = [
        OhlcvPoint("BTCUSD", "1m", start + timedelta(minutes=i), 100.0, 101.0, 99.0, 100.0 + i, 100.0)
        for i in range(15)
    ]

    assert detect_market_anomalies([]) == []
    assert isinstance(detect_market_anomalies(point_rows, min_baseline=12), list)
