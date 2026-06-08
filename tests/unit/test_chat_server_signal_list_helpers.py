from chat_server_signal_list_helpers import _build_price_delta_fallback_signals, _filter_signal_rows


def test_filter_signal_rows_applies_confidence_actionable_tradeable_and_grade():
    signals = [
        {"symbol": "BTC", "confidence": 80, "actionable": True, "tradeable": True, "signal_grade": "A"},
        {"symbol": "ETH", "confidence": 40, "actionable": True, "tradeable": True, "signal_grade": "A"},
        {"symbol": "SOL", "confidence": 90, "actionable": False, "tradeable": True, "signal_grade": "A"},
        {"symbol": "XRP", "confidence": 90, "actionable": True, "tradeable": False, "signal_grade": "A"},
        {"symbol": "GOLD", "confidence": 90, "actionable": True, "tradeable": True, "signal_grade": "B"},
    ]

    filtered = _filter_signal_rows(
        signals,
        min_confidence=70,
        actionable_only=True,
        tradeable_only=True,
        grade="a",
    )

    assert [signal["symbol"] for signal in filtered] == ["BTC"]


def test_build_price_delta_fallback_signals_builds_buy_sell_hold_and_watch():
    rows = [
        {"symbol": "BUY", "avg_price": 102, "total_volume": 240, "window_end": "t2"},
        {"symbol": "BUY", "avg_price": 100, "total_volume": 100, "window_end": "t1"},
        {"symbol": "SELL", "avg_price": 98, "total_volume": 240, "window_end": "t2"},
        {"symbol": "SELL", "avg_price": 100, "total_volume": 100, "window_end": "t1"},
        {"symbol": "HOLD", "avg_price": 100.01, "total_volume": 100, "window_end": "t2"},
        {"symbol": "HOLD", "avg_price": 100, "total_volume": 100, "window_end": "t1"},
        {"symbol": "WATCH", "avg_price": 100.2, "total_volume": 100, "window_end": "t2"},
        {"symbol": "WATCH", "avg_price": 100, "total_volume": 100, "window_end": "t1"},
        {"symbol": "SKIP", "avg_price": 100, "total_volume": 100, "window_end": "t1"},
    ]

    signals = _build_price_delta_fallback_signals(rows)
    by_symbol = {signal["symbol"]: signal for signal in signals}

    assert by_symbol["BUY"]["direction"] == "BUY"
    assert by_symbol["SELL"]["direction"] == "SELL"
    assert by_symbol["HOLD"]["direction"] == "HOLD"
    assert by_symbol["WATCH"]["direction"] == "WATCH"
    assert "SKIP" not in by_symbol
    assert by_symbol["BUY"]["confidence"] >= by_symbol["WATCH"]["confidence"]
    assert "Δ" in by_symbol["WATCH"]["reason"]
