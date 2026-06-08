from chat_server_best_setup_helpers import (
    _daily_risk_guard_summary,
    _build_setup_feedback_summary,
    _build_best_setup_metrics,
    _build_trade_memory_document,
    _best_setup_cache_key,
    _best_setup_entry_decision,
    _best_setup_int_env,
    _best_setup_recommendations,
    _best_setup_risk_summary,
    _best_setup_run_id,
    _best_outcome_label,
    _best_setup_score_explain,
    _pre_graph_rag_readiness_summary,
    _parse_percent_like,
    _telegram_format_feedback,
    _trade_memory_sync_error,
    _trade_memory_sync_skip,
    _trade_memory_sync_success,
)


def test_parse_percent_like_handles_strings_numbers_and_default():
    assert _parse_percent_like("25%") == 0.25
    assert _parse_percent_like(0.4) == 0.4
    assert _parse_percent_like("oops", default=0.7) == 0.7


def test_best_setup_int_env_applies_minimum_and_default(monkeypatch):
    monkeypatch.setenv("BEST_SETUP_TEST_VALUE", "5")
    assert _best_setup_int_env("BEST_SETUP_TEST_VALUE", 10, 8) == 8

    monkeypatch.setenv("BEST_SETUP_TEST_VALUE", "invalid")
    assert _best_setup_int_env("BEST_SETUP_TEST_VALUE", 10, 8) == 10


def test_best_setup_cache_key_normalizes_symbols():
    key = _best_setup_cache_key([" btc ", "", "gold"], lambda symbol: str(symbol).strip().upper())
    assert key == "BTC,GOLD"
    assert _best_setup_cache_key(["", "   "], lambda symbol: symbol) == "default"


def test_best_setup_entry_decision_handles_blocked_incomplete_and_buy_paths():
    blocked = _best_setup_entry_decision(
        {"symbol": "BTC", "side": "BUY"},
        graph_guard_fn=lambda symbol, side: {"reason": "weak history", "blockers": ["x"]},
        num_fn=float,
    )
    assert blocked["action"] == "WAIT_GRAPH_BLOCKED"

    incomplete = _best_setup_entry_decision(
        {"symbol": "BTC", "side": "BUY", "price": 100, "entry_zone": {"low": None, "high": 110}},
        graph_guard_fn=lambda symbol, side: {"status": "OK"},
        num_fn=lambda value: float(value) if value is not None else 0.0,
    )
    assert incomplete == {"action": "WAIT", "reason": "entry zone is incomplete", "rr": None}

    inside_buy = _best_setup_entry_decision(
        {
            "symbol": "BTC",
            "side": "BUY",
            "price": 105,
            "entry_zone": {"low": 100, "high": 110},
            "stop_loss": 95,
            "take_profit_1": 120,
        },
        graph_guard_fn=lambda symbol, side: {"status": "OK", "reason": "clear"},
        num_fn=float,
    )
    assert inside_buy["action"] == "ENTER_NOW"
    assert inside_buy["rr"] == 1.5


def test_best_setup_entry_decision_handles_sell_and_rr_override():
    sell_pullback = _best_setup_entry_decision(
        {
            "symbol": "ETH",
            "side": "SELL",
            "price": 90,
            "entry_zone": {"low": 100, "high": 110},
            "stop_loss": 120,
            "take_profit_1": 80,
        },
        graph_guard_fn=lambda symbol, side: {"status": "OK"},
        num_fn=float,
    )
    assert sell_pullback["action"] == "WAIT_PULLBACK"

    poor_rr = _best_setup_entry_decision(
        {
            "symbol": "ETH",
            "side": "SELL",
            "price": 105,
            "entry_zone": {"low": 100, "high": 110},
            "stop_loss": 115,
            "take_profit_1": 102,
        },
        graph_guard_fn=lambda symbol, side: {"status": "OK"},
        num_fn=float,
    )
    assert poor_rr["action"] == "WAIT_BETTER_RR"
    assert "only" in poor_rr["reason"]


def test_best_setup_entry_decision_handles_buy_wait_confirm_and_no_direction():
    buy_pullback = _best_setup_entry_decision(
        {
            "symbol": "BTC",
            "side": "BUY",
            "price": 115,
            "entry_zone": {"low": 100, "high": 110},
            "stop_loss": 90,
            "take_profit_1": 140,
        },
        graph_guard_fn=lambda symbol, side: {"status": "OK"},
        num_fn=float,
    )
    assert buy_pullback["action"] == "WAIT_PULLBACK"

    buy_wait = _best_setup_entry_decision(
        {
            "symbol": "BTC",
            "side": "BUY",
            "price": 95,
            "entry_zone": {"low": 100, "high": 110},
            "stop_loss": 90,
            "take_profit_1": 130,
        },
        graph_guard_fn=lambda symbol, side: {"status": "OK"},
        num_fn=float,
    )
    assert buy_wait["action"] == "WAIT_CONFIRM"

    no_direction = _best_setup_entry_decision(
        {
            "symbol": "BTC",
            "side": "HOLD",
            "price": 105,
            "entry_zone": {"low": 100, "high": 110},
            "stop_loss": 95,
            "take_profit_1": 120,
        },
        graph_guard_fn=lambda symbol, side: {"status": "OK"},
        num_fn=float,
    )
    assert no_direction["action"] == "WAIT"
    assert no_direction["reason"] == "no directional setup"


def test_best_setup_entry_decision_handles_sell_wait_confirm():
    sell_wait = _best_setup_entry_decision(
        {
            "symbol": "ETH",
            "side": "SELL",
            "price": 112,
            "entry_zone": {"low": 100, "high": 110},
            "stop_loss": 118,
            "take_profit_1": 80,
        },
        graph_guard_fn=lambda symbol, side: {"status": "OK"},
        num_fn=float,
    )
    assert sell_wait["action"] == "WAIT_CONFIRM"


def test_best_setup_score_explain_clips_and_marks_model_trust():
    trusted = _best_setup_score_explain(
        confidence=0.8,
        win_prob=0.6,
        win_rate=0.55,
        avg_pnl=4.0,
        feedback_adjustment=0.1,
        weights={
            "confidence": 0.4,
            "ml_win_probability": 0.3,
            "paper_win_rate": 0.2,
            "paper_avg_pnl": 0.1,
        },
        model_trust={"trusted": True},
    )
    assert trusted["total"] == 0.81
    assert trusted["components"]["paper_avg_pnl"] == 0.1
    assert trusted["model_weighted"] is True

    degraded = _best_setup_score_explain(
        confidence=0.0,
        win_prob=0.0,
        win_rate=0.0,
        avg_pnl=-5.0,
        feedback_adjustment=-0.5,
        weights={},
        model_trust={"trusted": False},
    )
    assert degraded["total"] == 0.0
    assert degraded["model_weighted"] is False
    assert "degraded" in degraded["model_note"]


def test_best_setup_risk_summary_handles_missing_inputs_and_basic_fallback():
    missing = _best_setup_risk_summary(
        {"entry_zone": {"low": None, "high": 110}, "stop_loss": 95},
        num_fn=lambda value: float(value) if value is not None else 0.0,
    )
    assert missing == {"available": False, "reason": "missing entry or stop loss"}

    basic = _best_setup_risk_summary(
        {"entry_zone": {"low": 100, "high": 110}, "stop_loss": 95},
        num_fn=float,
        account_summary={"balance": 2000},
        chat_id="chat-1",
        profile_getter=lambda chat_id: {"risk_pct": 2.5},
    )
    assert basic["available"] is True
    assert basic["account_balance"] == 2000.0
    assert basic["risk_percent"] == 2.5
    assert basic["risk_amount"] == 50.0
    assert basic["entry_mid"] == 105.0
    assert basic["note"] == "basic risk estimate"


def test_best_setup_risk_summary_handles_profile_errors_and_calculator_paths():
    profile_error = _best_setup_risk_summary(
        {"entry_zone": {"low": 100, "high": 110}, "stop_loss": 95},
        num_fn=float,
        account_summary={"equity": 5000},
        chat_id="chat-2",
        profile_getter=lambda chat_id: (_ for _ in ()).throw(RuntimeError("boom")),
        calculator=lambda **kwargs: {
            "account_balance_usdt": kwargs["account_balance_usdt"],
            "risk_percent": kwargs["risk_percent"],
            "risk_usdt": 50.0,
            "entry_price": kwargs["entry_price"],
            "stop_loss_price": kwargs["stop_loss_price"],
            "sl_distance_pct": 0.1,
            "position_size_units": 2.0,
            "position_value_usdt": 210.0,
            "margin_required_usdt": 21.0,
            "risk_level": "medium",
        },
    )
    assert profile_error["available"] is True
    assert profile_error["risk_percent"] == 1.0
    assert profile_error["risk_level"] == "medium"
    assert "broker lot conversion" in profile_error["note"]

    calc_exception = _best_setup_risk_summary(
        {"entry_zone": {"low": 100, "high": 110}, "stop_loss": 95},
        num_fn=float,
        calculator=lambda **kwargs: (_ for _ in ()).throw(ValueError("calc boom")),
    )
    assert calc_exception == {"available": False, "reason": "calc boom"}

    calc_error = _best_setup_risk_summary(
        {"entry_zone": {"low": 100, "high": 110}, "stop_loss": 95},
        num_fn=float,
        calculator=lambda **kwargs: {"error": "bad config"},
    )
    assert calc_error == {"available": False, "reason": "bad config"}

    calc_invalid = _best_setup_risk_summary(
        {"entry_zone": {"low": 100, "high": 110}, "stop_loss": 95},
        num_fn=float,
        calculator=lambda **kwargs: None,
    )
    assert calc_invalid == {"available": False, "reason": "risk calculation failed"}


def test_best_setup_run_id_uses_payload_timestamp_or_now():
    from_payload = _best_setup_run_id(
        {"generated_at": "2026-05-26T14:23:45+00:00"},
        {"symbol": "BTC", "side": "BUY", "score": 0.9876},
    )
    assert from_payload == "2026-05-26T14:23:BTC:BUY:0.988"

    fallback = _best_setup_run_id(
        {},
        {"symbol": "ETH", "side": "SELL", "score": 1},
        now_fn=lambda: "2026-05-26T15:01:00+00:00",
    )
    assert fallback == "2026-05-26T15:01:ETH:SELL:1.0"


def test_best_outcome_label_handles_unknown_buy_sell_and_flat_paths():
    assert _best_outcome_label({"price": 0, "side": "BUY", "stop_loss": 90, "take_profit_1": 110}, 100) == ("UNKNOWN", 0.0)

    buy_tp1 = _best_outcome_label({"price": 100, "side": "BUY", "stop_loss": 95, "take_profit_1": 110}, 110)
    assert buy_tp1[0] == "TP1"
    assert round(buy_tp1[1], 4) == 0.1

    buy_sl = _best_outcome_label({"price": 100, "side": "BUY", "stop_loss": 95, "take_profit_1": 110}, 94)
    assert buy_sl[0] == "SL"

    sell_tp1 = _best_outcome_label({"price": 100, "side": "SELL", "stop_loss": 105, "take_profit_1": 90}, 90)
    assert sell_tp1[0] == "TP1"

    sell_sl = _best_outcome_label({"price": 100, "side": "SELL", "stop_loss": 105, "take_profit_1": 90}, 106)
    assert sell_sl[0] == "SL"

    win = _best_outcome_label({"price": 100, "side": "BUY", "stop_loss": 95, "take_profit_1": 150}, 103)
    loss = _best_outcome_label({"price": 100, "side": "BUY", "stop_loss": 95, "take_profit_1": 150}, 99)
    flat = _best_outcome_label({"price": 100, "side": "HOLD", "stop_loss": 0, "take_profit_1": 0}, 100)
    assert win[0] == "WIN"
    assert loss[0] == "LOSS"
    assert flat[0] == "FLAT"


def test_best_setup_recommendations_handles_low_sample_low_win_rate_and_symbol_throttle():
    low_sample = _best_setup_recommendations({"horizons": {"4h": {"evaluated": 10}}, "by_symbol": {}})
    assert low_sample == ["Collect at least 30 evaluated /best snapshots before trusting precision claims."]

    low_win_rate = _best_setup_recommendations(
        {
            "horizons": {"4h": {"evaluated": 35, "win_rate": 0.4}},
            "by_symbol": {"BTC": {"evaluated_4h": 5, "win_rate_4h": 0.39}},
        }
    )
    assert "Keep /best in watch/paper mode; 4h win rate is below 50%." in low_win_rate
    assert "Throttle symbols with weak 4h outcome records." in low_win_rate

    healthy = _best_setup_recommendations(
        {
            "horizons": {"4h": {"evaluated": 40, "win_rate": 0.65}},
            "by_symbol": {"BTC": {"evaluated_4h": 5, "win_rate_4h": 0.5}},
        }
    )
    assert healthy == []


def test_build_best_setup_metrics_summarizes_rows_and_recent_items():
    rows = [
        {
            "created_at": "2026-05-26T10:00:00+00:00",
            "symbol": "BTC",
            "side": "BUY",
            "score": 0.9,
            "decision_action": "ENTER_NOW",
            "no_trade": 0,
            "outcome_1h": "WIN",
            "return_1h": 0.01,
            "outcome_4h": "TP1",
            "return_4h": 0.03,
            "outcome_24h": None,
            "return_24h": None,
        },
        {
            "created_at": "2026-05-26T11:00:00+00:00",
            "symbol": "ETH",
            "side": "SELL",
            "score": 0.7,
            "decision_action": "WAIT",
            "no_trade": 1,
            "outcome_1h": "LOSS",
            "return_1h": -0.02,
            "outcome_4h": "LOSS",
            "return_4h": -0.01,
            "outcome_24h": "FLAT",
            "return_24h": 0.0,
        },
    ]
    metrics = _build_best_setup_metrics(rows, {"checked": 2, "updated": 1}, {"1h": 1, "4h": 4, "24h": 24})
    assert metrics["total_snapshots"] == 2
    assert metrics["evaluation"]["updated"] == 1
    assert metrics["horizons"]["1h"]["evaluated"] == 2
    assert metrics["horizons"]["1h"]["wins"] == 1
    assert metrics["by_symbol"]["BTC"]["win_rate_4h"] == 1.0
    assert metrics["recent"][1]["symbol"] == "ETH"
    assert metrics["recommendations"][0].startswith("Collect at least 30 evaluated")


def test_build_trade_memory_document_renders_sections_and_blockers():
    rendered = _build_trade_memory_document(
        {
            "horizons": {"4h": {"evaluated": 12, "wins": 7, "losses": 5, "win_rate": 0.5833, "avg_return": 0.0123}},
            "by_symbol": {"BTC": {"snapshots": 5, "evaluated_4h": 5, "win_rate_4h": 0.6, "avg_return_4h": 0.02}},
        },
        {"total": 4, "by_rating": {"good": 3}, "score_adjustments": {"BTC:BUY": 0.1}},
        {"status": "blocked", "paper_pnl_usd_today": -120.0, "opened_trades_today": 5, "max_daily_trades": 10, "open_trades": 2, "blockers": ["daily loss"]},
        generated_at="2026-05-26T12:00:00+00:00",
    )
    assert "CryptoStream AI trade memory" in rendered
    assert "Generated at: 2026-05-26T12:00:00+00:00" in rendered
    assert "- 4h: evaluated=12, wins=7, losses=5" in rendered
    assert "- BTC: snapshots=5, evaluated_4h=5" in rendered
    assert "BTC:BUY: score_adjustment=+0.1000" in rendered
    assert "blockers=['daily loss']" in rendered
    assert "Operational rules learned:" in rendered


def test_daily_risk_guard_summary_handles_ok_watch_and_blocked_states():
    ok = _daily_risk_guard_summary(
        balance=10000.0,
        daily_loss_limit_pct=2.0,
        max_daily_trades=10,
        today="2026-05-26",
        closed={"trades": 2, "pnl_usd": 50.0},
        opened={"trades": 3},
        open_row={"open_trades": 1},
    )
    assert ok["status"] == "ok"
    assert ok["daily_loss_limit_usd"] == 200.0

    watch = _daily_risk_guard_summary(
        balance=10000.0,
        daily_loss_limit_pct=2.0,
        max_daily_trades=10,
        today="2026-05-26",
        closed={"trades": 2, "pnl_usd": -160.0},
        opened={"trades": 3},
        open_row={"open_trades": 1},
        chat_id="abc",
    )
    assert watch["status"] == "watch"
    assert watch["warnings"] == ["daily loss is near the configured limit"]
    assert watch["chat_id"] == "abc"

    blocked = _daily_risk_guard_summary(
        balance=10000.0,
        daily_loss_limit_pct=2.0,
        max_daily_trades=5,
        today="2026-05-26",
        closed={"trades": 4, "pnl_usd": -250.0},
        opened={"trades": 5},
        open_row={"open_trades": 2},
    )
    assert blocked["status"] == "blocked"
    assert len(blocked["blockers"]) == 2


def test_build_setup_feedback_summary_handles_empty_and_weighted_adjustments():
    empty = _build_setup_feedback_summary([])
    assert empty["total"] == 0
    assert empty["recommendations"] == [
        "No Telegram setup feedback yet. Use /best and press Good/Bad/Too late/Wrong direction."
    ]

    rows = [
        {"symbol": "BTC", "side": "BUY", "rating": "GOOD", "source": "tg", "score": 0.9, "created_at": "2026-05-26T10:00:00+00:00"},
        {"symbol": "BTC", "side": "BUY", "rating": "BAD", "source": "tg", "score": 0.7, "created_at": "2026-05-26T11:00:00+00:00"},
        {"symbol": "ETH", "side": "SELL", "rating": "WRONG", "source": "tg", "score": 0.4, "created_at": "2026-05-26T12:00:00+00:00"},
    ]
    summary = _build_setup_feedback_summary(rows)
    assert summary["total"] == 3
    assert summary["by_rating"]["GOOD"] == 1
    assert summary["by_symbol_side"]["BTC:BUY"]["count"] == 2
    assert summary["score_adjustments"]["BTC:BUY"] == 0.0
    assert summary["score_adjustments"]["ETH:SELL"] < 0
    assert "Downgrade setups with negative human feedback:" in summary["recommendations"][0]


def test_telegram_format_feedback_handles_unavailable_and_ranked_output():
    unavailable = _telegram_format_feedback({"available": False, "error": "db down"})
    assert unavailable == "Feedback diagnostics unavailable: db down"

    rendered = _telegram_format_feedback(
        {
            "available": True,
            "total": 2,
            "by_rating": {"GOOD": 1, "BAD": 1},
            "by_symbol_side": {
                "BTC:BUY": {"symbol": "BTC", "side": "BUY", "score_adjustment": -0.08, "ratings": {"BAD": 1}},
                "ETH:SELL": {"symbol": "ETH", "side": "SELL", "score_adjustment": 0.08, "ratings": {"GOOD": 1}},
            },
            "recent": [{"symbol": "BTC", "side": "BUY", "rating": "BAD", "created_at": "2026-05-26T12:00:00+00:00"}],
            "recommendations": ["Downgrade setups with negative human feedback: BTC BUY"],
        }
    )
    assert "Telegram feedback learning" in rendered
    assert "Most downgraded:" in rendered
    assert "Most favored:" in rendered
    assert "Recent:" in rendered
    assert "Downgrade setups with negative human feedback: BTC BUY" in rendered


def test_trade_memory_sync_helpers_build_skip_success_and_error_payloads():
    skipped = _trade_memory_sync_skip("2026-05-26T12:00:00+00:00", {"chunks": 3})
    assert skipped["status"] == "SKIPPED"
    assert skipped["last_result"] == {"chunks": 3}

    state_update, response = _trade_memory_sync_success(10.0, "2026-05-26T12:00:00+00:00", {"chunks": 3})
    assert state_update["last_sync_epoch"] == 10.0
    assert state_update["last_error"] is None
    assert response["status"] == "OK"

    state_update, response = _trade_memory_sync_error(11.0, "2026-05-26T12:01:00+00:00", "boom")
    assert state_update["last_error"] == "boom"
    assert response == {"status": "ERROR", "error": "boom", "no_extra_embedding_cost": True}


def test_pre_graph_rag_readiness_summary_handles_blocked_and_ready_cases():
    blocked = _pre_graph_rag_readiness_summary(
        {"total_snapshots": 10, "horizons": {"1h": {"evaluated": 5}, "4h": {"evaluated": 4}, "24h": {"evaluated": 1}}},
        {"total": 2},
        {"status": "ERROR", "error": "db down"},
        {"last_sync_at": None},
        {"last_result": "pending"},
        {"last_result": "idle"},
        best_outcome_eval_interval_seconds=900,
        trade_memory_sync_interval_seconds=1800,
        trade_graph_rebuild_interval_seconds=1800,
    )
    assert blocked["ready_for_graph_rag"] is False
    assert len(blocked["blockers"]) == 4
    assert blocked["current"]["feedback_labels"] == 2

    ready = _pre_graph_rag_readiness_summary(
        {"total_snapshots": 120, "horizons": {"1h": {"evaluated": 50}, "4h": {"evaluated": 40}, "24h": {"evaluated": 20}}},
        {"total": 35},
        {"status": "OK", "docs": 99},
        {"last_sync_at": "2026-05-26T12:00:00+00:00", "last_result": {"chunks": 3}},
        {"last_result": "ok"},
        {"last_result": "ok"},
        best_outcome_eval_interval_seconds=900,
        trade_memory_sync_interval_seconds=1800,
        trade_graph_rebuild_interval_seconds=1800,
    )
    assert ready["ready_for_graph_rag"] is True
    assert ready["blockers"] == []
    assert ready["current"]["evaluated_4h"] == 40
    assert ready["background_tasks"]["trade_memory_sync_interval_seconds"] == 1800
