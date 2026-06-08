from chat_server_payload_helpers import (
    _calendar_has_content,
    _etf_flows_has_content,
    _has_non_empty_sequence,
    _market_indices_has_content,
    _market_sentiment_has_content,
    _market_stocks_has_content,
    _metric_label,
    _metric_number,
    _payload_updated_at,
    _utc_now_iso,
    _with_data_quality,
)


def test_metric_label_and_number_helpers():
    assert _metric_label("Hello world!") == "Hello_world_"
    assert _metric_label("") == "unknown"
    assert _metric_number("12.5") == 12.5
    assert _metric_number("bad") == 0.0


def test_payload_updated_at_prefers_payload_and_meta():
    assert _payload_updated_at({"updated_at": "2026-05-26T00:00:00Z"}) == "2026-05-26T00:00:00Z"
    assert _payload_updated_at({"_meta": {"updated_at": "2026-05-27T00:00:00Z"}}) == "2026-05-27T00:00:00Z"
    assert _payload_updated_at({}, fallback_ts=1700000000).endswith("Z")
    assert _utc_now_iso().endswith("Z")


def test_with_data_quality_wraps_dict_and_list_payloads():
    wrapped_dict = _with_data_quality(
        {"items": [1]},
        cache_key="abc",
        status="ok",
        data_quality="live",
        source="cache",
        warning="warn",
        details={"x": 1},
    )
    wrapped_list = _with_data_quality(
        [1, 2],
        cache_key=None,
        status="stale",
        data_quality="stale",
        source="fallback",
        error="down",
    )

    assert wrapped_dict["_meta"]["cache_key"] == "abc"
    assert wrapped_dict["status"] == "OK"
    assert wrapped_dict["warning"] == "warn"
    assert wrapped_list["data"] == [1, 2]
    assert wrapped_list["error"] == "down"
    assert wrapped_list["_meta"]["is_stale"] is True


def test_content_helpers_detect_presence():
    assert _has_non_empty_sequence([1]) is True
    assert _has_non_empty_sequence([]) is False
    assert _market_sentiment_has_content({"articles": [1]}) is True
    assert _market_sentiment_has_content({"overall": {"summary": "up"}}) is True
    assert _market_sentiment_has_content({"overall": {"score": 10}}) is True
    assert _market_indices_has_content({"spx": {"price": 1}}) is True
    assert _market_stocks_has_content({"nvda": {"price": 1}}) is True
    assert _etf_flows_has_content({"flows": [1]}) is True
    assert _calendar_has_content({"events": [1]}) is True
    assert _calendar_has_content({"macro_watch": [1]}) is True
    assert _calendar_has_content({"trading_note": "watch CPI"}) is True
