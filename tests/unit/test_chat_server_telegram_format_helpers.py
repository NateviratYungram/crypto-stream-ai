from chat_server_telegram_format_helpers import (
    _telegram_blocked_trade_keyboard,
    _telegram_extract_blockers,
    _telegram_format_blocked_detail,
    _telegram_format_blocked_trade,
    _telegram_format_mt5_snapshot,
    _telegram_format_paper_dashboard,
    _telegram_trade_keyboard,
)


def _num(value):
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def test_telegram_format_mt5_snapshot_handles_empty_and_positions():
    assert "not synced" in _telegram_format_mt5_snapshot({})

    rendered = _telegram_format_mt5_snapshot(
        {
            "connected": True,
            "summary": {
                "login": 123,
                "company": "Broker",
                "balance": 1000,
                "equity": 1010,
                "currency": "USD",
                "trade_allowed": True,
                "trade_expert": False,
            },
            "positions": [{"symbol": "GOLD", "type": "BUY", "volume": 0.01, "profit": 3.2}],
        }
    )

    assert "MT5 account" in rendered
    assert "- Connected: True" in rendered
    assert "GOLD BUY vol=0.01 pnl=3.2" in rendered


def test_telegram_format_paper_dashboard_renders_progress_feedback_quality_and_open_trades():
    rendered = _telegram_format_paper_dashboard(
        gate={
            "live_ready": False,
            "mode": "paper",
            "blockers": ["labels"],
            "paper_label_progress": {"current": 42, "target": 100},
        },
        status={
            "enabled": True,
            "shadow_labeling_enabled": True,
            "scan_interval_seconds": 60,
            "cooldown_minutes": 10,
            "max_open_positions": 3,
            "last_summary": {"expired_labels": {"closed_count": 2}},
        },
        snapshot={
            "summary": {
                "open_count": 1,
                "closed_count": 9,
                "wins": 5,
                "losses": 4,
                "win_rate": 0.55,
                "profit_factor": 999.0,
                "expectancy_usd": 1.2,
                "closed_pnl_usd": 10.0,
                "open_unrealized_pnl_usd": 1.5,
            },
            "open_trades": [{"symbol": "BTCUSD", "side": "BUY", "volume": 0.01, "entry_price": 65000, "pnl_usd": 2.5}],
        },
        feedback={
            "symbol": {
                "BTCUSD": {"trades": 3, "pnl": 12.0, "win_rate": 66.6},
                "ETHUSD": {"trades": 3, "pnl": -5.0, "win_rate": 33.3},
            }
        },
        quality={"included": 7, "excluded": 2, "reasons": {"feature_coverage_low": 2}},
        num_fn=_num,
    )

    assert "Paper AI dashboard" in rendered
    assert "- Remaining: 58 labels" in rendered
    assert "- Profit factor: inf" in rendered
    assert "- Weakest symbol: ETHUSD" in rendered
    assert "- Strongest symbol: BTCUSD" in rendered
    assert "- Top pruning reason: feature_coverage_low (2)" in rendered
    assert "BTCUSD BUY vol=0.01 entry=65000.00000 pnl=+2.50" in rendered


def test_trade_keyboards_and_blocker_extraction():
    confirm = _telegram_trade_keyboard("abc123")
    blocked = _telegram_blocked_trade_keyboard("abc123")

    assert confirm["inline_keyboard"][0][0]["callback_data"] == "tg:trade_confirm:abc123"
    assert blocked["inline_keyboard"][0][0]["callback_data"] == "tg:why_blocked:abc123"
    assert _telegram_extract_blockers({"readiness": {"blockers": ["paper labels"]}}) == [
        {"name": "paper labels", "detail": ""}
    ]
    assert _telegram_extract_blockers({"preflight": {"issues": ["spread too wide"]}}) == [
        {"name": "preflight", "detail": "spread too wide"}
    ]
    assert _telegram_extract_blockers({}) == []


def test_format_blocked_trade_and_detail():
    result = {
        "status": "BLOCKED",
        "message": "quality gate",
        "readiness": {"blockers": [{"name": "paper_labels", "detail": "need more labels"}]},
    }
    gate = {"paper_label_progress": {"current": 12, "target": 50}}
    rendered = _telegram_format_blocked_trade("abc123", result, gate)
    detail = _telegram_format_blocked_detail(
        "abc123",
        {"symbol": "GOLD", "side": "BUY", "volume": 0.01, "sl": 2300, "tp": 2350},
        result,
        gate,
    )

    assert "Live order blocked safely." in rendered
    assert "- paper labels: need more labels" in rendered
    assert "AI progress: 12/50 closed paper labels" in rendered
    assert "Why blocked: abc123" in detail
    assert "- SL/TP: 2300 / 2350" in detail


def test_format_blocked_trade_handles_missing_details():
    rendered = _telegram_format_blocked_trade("abc123", {})

    assert "Safety gate did not provide detailed blockers" in rendered
    assert "Live order blocked by safety gate" in rendered
