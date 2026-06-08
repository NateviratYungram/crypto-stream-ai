from chat_server_signal_helpers import _telegram_format_signal


def test_telegram_format_signal_handles_error_and_invalid_payload():
    assert "Signal error for BTC: down" == _telegram_format_signal(
        "BTC",
        {"error": "down"},
        lambda symbol, side: {"status": "SKIPPED", "reason": "unused"},
    )
    assert "Signal error for BTC: invalid result" == _telegram_format_signal(
        "BTC",
        None,
        lambda symbol, side: {"status": "SKIPPED", "reason": "unused"},
    )


def test_telegram_format_signal_renders_trade_plan_with_guard_blocker():
    rendered = _telegram_format_signal(
        "BTC",
        {
            "symbol": "BTCUSD",
            "recommendation": "buy",
            "price": 65000,
            "entry_zone": {"low": 64500, "high": 64800},
            "stop_loss": 63900,
            "take_profit_1": 66000,
            "take_profit_2": 66800,
            "ai_edge": {"signal_confidence": 0.82, "win_pct": 61},
            "best_persona": "Trend continuation",
        },
        lambda symbol, side: {"status": "BLOCKED", "reason": "counter trend", "blockers": ["wall"]},
    )

    assert "Trade plan: BTCUSD" in rendered
    assert "- Signal: BUY" in rendered
    assert "- Graph guard: BLOCKED | counter trend" in rendered
    assert "- Entry: 64500 - 64800" in rendered
    assert "- Confidence: 0.82" in rendered
    assert "Graph RAG says do not trade this setup now" in rendered


def test_telegram_format_signal_handles_hold_and_probability_fallback():
    rendered = _telegram_format_signal(
        "XAUUSD",
        {
            "recommendation": "hold",
            "price": 2300,
            "entry_zone": {},
            "stop_loss": None,
            "take_profit_1": None,
            "take_profit_2": None,
            "ai_edge": {"signal_confidence": 0.4, "win_probability": 0.51},
        },
        lambda symbol, side: {"status": "OK", "reason": "unused"},
    )

    assert "- Signal: HOLD" in rendered
    assert "skipped for HOLD/no-direction signal" in rendered
    assert "- Win probability: 0.51" in rendered
    assert "- Note: Institutional setup" in rendered
    assert "This is analysis only until live quality gates pass." in rendered
