import pytest

from chat_server_alert_helpers import (
    _build_best_confirmation_alert_request,
    _build_best_entry_alert_request,
    _telegram_parse_alert_request,
)


def _num(value):
    return float(value or 0.0)


def test_telegram_parse_alert_request_handles_explicit_conditions_and_missing_data():
    symbol_calls = []

    def extract_symbol(raw, default):
        symbol_calls.append(raw)
        return "ETH"

    above = _telegram_parse_alert_request(
        "/alert BTC above 70,000",
        symbol_extractor=extract_symbol,
        live_price_fn=lambda symbol: 0,
    )
    below = _telegram_parse_alert_request(
        "alert eth below 1900",
        symbol_extractor=extract_symbol,
        live_price_fn=lambda symbol: 0,
    )

    assert above["symbol"] == "BTC"
    assert above["condition"] == "above"
    assert above["price"] == 70000.0
    assert below["symbol"] == "ETH"
    assert below["condition"] == "below"
    assert _telegram_parse_alert_request("watch BTC 70000", symbol_extractor=extract_symbol, live_price_fn=lambda symbol: 0) is None
    assert _telegram_parse_alert_request("alert BTC", symbol_extractor=extract_symbol, live_price_fn=lambda symbol: 0) is None
    assert _telegram_parse_alert_request("alert now 70000", symbol_extractor=lambda raw, default: "", live_price_fn=lambda symbol: 0) is None
    assert _telegram_parse_alert_request("alert BTC 0", symbol_extractor=extract_symbol, live_price_fn=lambda symbol: 0) is None


def test_telegram_parse_alert_request_infers_condition_from_live_price():
    above = _telegram_parse_alert_request(
        "alert BTC 120",
        symbol_extractor=lambda raw, default: "BTC",
        live_price_fn=lambda symbol: 100,
    )
    below = _telegram_parse_alert_request(
        "alert BTC 80",
        symbol_extractor=lambda raw, default: "BTC",
        live_price_fn=lambda symbol: 100,
    )

    assert above["condition"] == "above"
    assert below["condition"] == "below"


def test_build_best_entry_alert_request_for_buy_sell_and_neutral():
    payload = {"no_trade": True, "no_trade_reason": "graph blocked"}
    buy = _build_best_entry_alert_request(
        {"symbol": "BTCUSD", "side": "BUY", "price": 110, "entry_zone": {"low": 95, "high": 100}, "entry_decision": {"action": "WAIT_PULLBACK"}},
        payload,
        num_fn=_num,
    )
    sell = _build_best_entry_alert_request(
        {"symbol": "GOLD", "side": "SELL", "price": 80, "entry_zone": {"low": 95, "high": 100}, "entry_decision": {"action": "WAIT_PULLBACK"}},
        {},
        num_fn=_num,
    )
    neutral = _build_best_entry_alert_request(
        {"symbol": "ETHUSD", "side": "HOLD", "price": 99, "entry_zone": {"low": 95, "high": 105}},
        {},
        num_fn=_num,
    )

    assert buy["condition"] == "below"
    assert buy["price"] == 100.0
    assert buy["metadata"]["no_trade"] is True
    assert sell["condition"] == "above"
    assert sell["price"] == 95.0
    assert neutral["condition"] == "above"
    assert neutral["price"] == 100.0


def test_build_best_confirmation_alert_request_and_missing_entry_zone():
    buy = _build_best_confirmation_alert_request(
        {"symbol": "BTCUSD", "side": "BUY", "price": 90, "entry_zone": {"low": 95, "high": 100}, "entry_decision": {"action": "ENTER_NOW"}},
        {"no_trade_reason": None},
        num_fn=_num,
    )
    sell = _build_best_confirmation_alert_request(
        {"symbol": "GOLD", "side": "SELL", "price": 110, "entry_zone": {"low": 95, "high": 100}},
        {},
        num_fn=_num,
    )
    neutral = _build_best_confirmation_alert_request(
        {"symbol": "ETHUSD", "side": "HOLD", "price": 100, "entry_zone": {"low": 95, "high": 105}},
        {},
        num_fn=_num,
    )

    assert buy["condition"] == "above"
    assert buy["price"] == 95.0
    assert buy["metadata"]["confirmation_required"] is True
    assert sell["condition"] == "below"
    assert sell["price"] == 100.0
    assert neutral["condition"] == "above"
    assert neutral["price"] == 100.0
    with pytest.raises(ValueError, match="complete entry zone"):
        _build_best_entry_alert_request({"symbol": "BTCUSD", "entry_zone": {"low": 95}}, {}, num_fn=_num)
    with pytest.raises(ValueError, match="complete entry zone"):
        _build_best_confirmation_alert_request({"symbol": "BTCUSD", "entry_zone": {"low": 95}}, {}, num_fn=_num)
