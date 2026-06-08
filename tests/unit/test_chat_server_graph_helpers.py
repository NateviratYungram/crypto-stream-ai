from chat_server_graph_helpers import (
    _best_paper_entry_reason,
    _build_best_alternative_candidates_payload,
    _build_signal_snapshot_metrics,
    _build_signal_snapshot_record,
    _build_trade_graph_guard_result,
    _current_market_regime,
    _format_best_alternative_report,
    _format_open_best_paper_blocked_exception,
    _format_open_best_paper_result,
    _format_trade_graph_report,
    _format_why_setup_report,
    _precheck_open_best_paper_payload,
    _resolve_best_paper_volume,
    _setup_node_key,
    _signal_outcome_label,
    _signal_snapshot_id,
    _trade_graph_key,
)


def _guard_thresholds():
    return {
        "min_evaluated": 5,
        "min_win_rate": 0.35,
        "min_avg_return": -0.005,
        "quarantine_adjustment": -0.12,
    }


def _simple_canonical_symbol(raw):
    return str(raw or "").upper().strip()


def test_trade_graph_key_helpers_normalize_parts():
    assert _trade_graph_key("setup", "btc usd", "buy") == "setup:BTC_USD:BUY"
    assert _setup_node_key("ethusd", "sell") == "setup:ETHUSD:SELL"
    assert len(_signal_snapshot_id("BTCUSD", "BUY", "15m", "scanner", "2026-06-02T10:12:30+00:00")) == 16


def test_current_market_regime_detects_risk_modes():
    risk_off = _current_market_regime({"macro": "fear dxy_up"}, now_fn=lambda: "2026-06-02T00:00:00+00:00")
    risk_on = _current_market_regime({"macro": "bull low_vol"}, now_fn=lambda: "2026-06-02T00:00:00+00:00")
    neutral = _current_market_regime({}, now_fn=lambda: "2026-06-02T00:00:00+00:00")

    assert risk_off["regime"] == "RISK_OFF"
    assert risk_on["regime"] == "RISK_ON"
    assert neutral["regime"] == "NEUTRAL"


def test_build_signal_snapshot_record_handles_skip_and_success():
    skipped = _build_signal_snapshot_record(
        {},
        "scanner",
        resolve_trade_symbol_fn=lambda symbol: {"canonical": symbol},
        num_fn=lambda value: 0,
        parse_percent_like_fn=lambda value, default=0.0: default,
        current_market_regime_fn=lambda: {"regime": "NEUTRAL"},
        trade_graph_guard_fn=lambda symbol, side: {"status": "OK"},
    )
    missing_price = _build_signal_snapshot_record(
        {"symbol": "ETHUSD", "recommendation": "moon", "price": 0},
        "scanner",
        resolve_trade_symbol_fn=lambda symbol: {"canonical": symbol},
        num_fn=lambda value: float(value or 0),
        parse_percent_like_fn=lambda value, default=0.0: default,
        current_market_regime_fn=lambda: {"regime": "NEUTRAL"},
        trade_graph_guard_fn=lambda symbol, side: {"status": "OK"},
    )

    success = _build_signal_snapshot_record(
        {
            "symbol": "btcusdt",
            "recommendation": "buy",
            "price": 65000,
            "signal_confidence": "82%",
            "win_probability": 0.61,
        },
        "scanner",
        timeframe="1h",
        resolve_trade_symbol_fn=lambda symbol: {"canonical": "BTCUSD"},
        num_fn=lambda value: float(value),
        parse_percent_like_fn=lambda value, default=0.0: 0.82 if value == "82%" else float(value or default),
        current_market_regime_fn=lambda: {"regime": "RISK_ON"},
        trade_graph_guard_fn=lambda symbol, side: {"status": "BLOCKED", "reason": "wall"},
        now_fn=lambda: "2026-06-02T10:12:30+00:00",
    )

    assert skipped == {"status": "SKIPPED", "reason": "missing_symbol"}
    assert missing_price == {"status": "SKIPPED", "reason": "missing_price", "symbol": "ETHUSD", "side": "HOLD"}
    assert success["status"] == "OK"
    assert success["canonical_symbol"] == "BTCUSD"
    assert success["side"] == "BUY"
    assert success["market_regime"] == "RISK_ON"
    assert "\"reason\": \"wall\"" in success["graph_guard_json"]


def test_signal_outcome_label_and_metrics_summary():
    assert _signal_outcome_label({"price": 100, "side": "BUY"}, 101) == ("WIN", 0.01)
    assert _signal_outcome_label({"price": 100, "side": "SELL"}, 101) == ("LOSS", -0.01)
    assert _signal_outcome_label({"price": 100, "side": "BUY"}, 100.1) == ("FLAT", 0.001)
    assert _signal_outcome_label({"price": 0, "side": "BUY"}, 101) == ("UNKNOWN", 0.0)

    metrics = _build_signal_snapshot_metrics(
        [
            {
                "canonical_symbol": "BTCUSD",
                "side": "BUY",
                "created_at": "2026-06-02T00:00:00+00:00",
                "price": 100,
                "source": "scanner",
                "market_regime": "RISK_ON",
                "outcome_4h": "WIN",
                "return_4h": 0.01,
            },
            {
                "canonical_symbol": "BTCUSD",
                "side": "BUY",
                "created_at": "2026-06-02T01:00:00+00:00",
                "price": 101,
                "source": "scanner",
                "market_regime": "RISK_ON",
                "outcome_4h": "LOSS",
                "return_4h": -0.02,
            },
            {
                "canonical_symbol": "ETHUSD",
                "side": "SELL",
                "created_at": "2026-06-02T02:00:00+00:00",
                "price": 200,
                "source": "scanner",
                "market_regime": "RISK_OFF",
                "outcome_4h": None,
                "return_4h": None,
            },
        ],
        {"status": "OK", "updated": 2},
    )

    assert metrics["total_signals"] == 3
    assert metrics["by_setup"]["BTCUSD:BUY"]["signals"] == 2
    assert metrics["by_setup"]["BTCUSD:BUY"]["win_rate_4h"] == 0.5
    assert metrics["by_setup"]["ETHUSD:SELL"]["evaluated_4h"] == 0
    assert len(metrics["recent"]) == 3


def test_build_trade_graph_guard_result_handles_missing_input_and_errors():
    missing = _build_trade_graph_guard_result(
        canonical="",
        original_symbol="raw",
        side_upper="",
        **_guard_thresholds(),
    )
    error = _build_trade_graph_guard_result(
        canonical="BTCUSD",
        side_upper="BUY",
        graph_error=RuntimeError("graph down"),
        **_guard_thresholds(),
    )

    assert missing["status"] == "INSUFFICIENT_DATA"
    assert missing["action"] == "ALLOW"
    assert missing["symbol"] == "raw"
    assert missing["side"] is None
    assert error["status"] == "ERROR"
    assert error["action"] == "ALLOW_WITH_CAUTION"
    assert error["warnings"] == ["graph down"]


def test_build_trade_graph_guard_result_handles_no_history_and_watch():
    no_history = _build_trade_graph_guard_result(
        canonical="BTCUSD",
        side_upper="SELL",
        graph={"query": {"symbol": "BTCUSD"}},
        setups=[],
        **_guard_thresholds(),
    )
    watch = _build_trade_graph_guard_result(
        canonical="ETHUSD",
        side_upper="BUY",
        graph={"query": {"symbol": "ETHUSD"}},
        setups=[
            {
                "setup": "ETHUSD:BUY",
                "evaluated_4h": 2,
                "win_rate_4h": 0.1,
                "avg_return_4h": -0.02,
                "feedback_adjustment": 0.0,
            }
        ],
        **_guard_thresholds(),
    )

    assert no_history["status"] == "INSUFFICIENT_DATA"
    assert no_history["action"] == "ALLOW_PAPER_ONLY"
    assert no_history["graph_query"] == {"symbol": "BTCUSD"}
    assert watch["status"] == "WATCH"
    assert watch["allowed"] is True
    assert watch["action"] == "ALLOW_WITH_CAUTION"
    assert watch["blockers"] == []
    assert "only 2 evaluated graph samples" in watch["reason"]


def test_build_trade_graph_guard_result_blocks_and_allows_by_thresholds():
    blocked = _build_trade_graph_guard_result(
        canonical="GOLD",
        side_upper="SELL",
        graph={"query": {"symbol": "GOLD"}},
        setups=[
            {
                "setup": "GOLD:SELL",
                "evaluated_4h": 20,
                "win_rate_4h": 0.2,
                "avg_return_4h": -0.02,
                "feedback_adjustment": -0.2,
            }
        ],
        **_guard_thresholds(),
    )
    allowed = _build_trade_graph_guard_result(
        canonical="SOLUSD",
        side_upper="BUY",
        graph={"query": {"symbol": "SOLUSD"}},
        setups=[
            {
                "setup": "SOLUSD:BUY",
                "evaluated_4h": 12,
                "win_rate_4h": 0.61234,
                "avg_return_4h": 0.0123459,
                "feedback_adjustment": 0.01349,
            }
        ],
        **_guard_thresholds(),
    )

    assert blocked["status"] == "BLOCKED"
    assert blocked["allowed"] is False
    assert blocked["action"] == "BLOCK_TRADE"
    assert len(blocked["blockers"]) == 3
    assert blocked["thresholds"]["min_win_rate"] == 0.35
    assert allowed["status"] == "OK"
    assert allowed["action"] == "ALLOW"
    assert allowed["reason"] == "graph history is acceptable"
    assert allowed["win_rate_4h"] == 0.6123
    assert allowed["avg_return_4h"] == 0.012346
    assert allowed["feedback_adjustment"] == 0.0135


def test_build_best_alternative_candidates_payload_ranks_trade_and_watch():
    guards = {
        ("BTC", "BUY"): {
            "symbol": "BTC",
            "status": "OK",
            "evaluated_4h": 10,
            "win_rate_4h": 0.6,
            "avg_return_4h": 0.01,
            "reason": "strong graph",
        },
        ("BTC", "SELL"): {
            "symbol": "BTC",
            "status": "OK",
            "evaluated_4h": 10,
            "win_rate_4h": 0.5,
            "avg_return_4h": 0.0,
            "warnings": ["thin edge"],
            "reason": "watch it",
        },
    }

    payload = _build_best_alternative_candidates_payload(
        profile_symbols=["", "btc", "BTC"],
        signal_metrics={"by_setup": {"BTC:BUY": {"evaluated_4h": 3, "signals": 5}}},
        risk_guard={"status": "OK", "blockers": []},
        trade_graph_guard_fn=lambda symbol, side: guards[(symbol, side)],
        canonical_symbol_fn=_simple_canonical_symbol,
        min_evaluated=5,
    )

    assert payload["decision"] == "TRADE"
    assert payload["best"]["symbol"] == "BTC"
    assert payload["best"]["side"] == "BUY"
    assert payload["best"]["mode"] == "TRADE_CANDIDATE"
    assert payload["best"]["evidence"] == 13
    assert payload["summary"] == {"trade_or_watch": 2, "paper_only": 0, "blocked": 0, "checked": 2}


def test_build_best_alternative_candidates_payload_falls_back_to_paper_only():
    payload = _build_best_alternative_candidates_payload(
        signal_metrics=None,
        risk_guard=None,
        default_symbols=["ETH"],
        trade_graph_guard_fn=lambda symbol, side: {
            "symbol": symbol,
            "status": "INSUFFICIENT_DATA",
            "evaluated_4h": 0,
            "reason": "collect evidence",
        },
        canonical_symbol_fn=_simple_canonical_symbol,
        min_evaluated=5,
    )

    assert payload["decision"] == "PAPER_ONLY"
    assert payload["best"]["mode"] == "PAPER_ONLY"
    assert payload["reason"] == "collect evidence"
    assert payload["summary"]["paper_only"] == 2


def test_build_best_alternative_candidates_payload_blocks_for_daily_guard_or_graph():
    daily_blocked = _build_best_alternative_candidates_payload(
        profile_symbols=["SOL"],
        signal_metrics={},
        risk_guard={"status": "BLOCKED", "blockers": ["daily cap"]},
        trade_graph_guard_fn=lambda symbol, side: {
            "symbol": symbol,
            "status": "OK",
            "evaluated_4h": 20,
            "win_rate_4h": 0.8,
            "avg_return_4h": 0.02,
            "reason": "good",
        },
        canonical_symbol_fn=_simple_canonical_symbol,
        min_evaluated=5,
    )
    graph_blocked = _build_best_alternative_candidates_payload(
        profile_symbols=["XRP"],
        signal_metrics={},
        risk_guard={"status": "OK", "blockers": []},
        trade_graph_guard_fn=lambda symbol, side: {
            "symbol": symbol,
            "status": "BLOCKED",
            "blockers": ["bad history"],
            "evaluated_4h": 20,
            "reason": "bad history",
        },
        canonical_symbol_fn=_simple_canonical_symbol,
        min_evaluated=5,
    )

    assert daily_blocked["decision"] == "NO_TRADE"
    assert daily_blocked["best"] is None
    assert daily_blocked["reason"] == "daily risk guard is blocked"
    assert daily_blocked["summary"]["blocked"] == 2
    assert graph_blocked["decision"] == "NO_TRADE"
    assert graph_blocked["reason"] == "all tested setup directions are blocked by Graph RAG guard"
    assert graph_blocked["summary"]["blocked"] == 2


def test_format_trade_graph_report_handles_no_history_for_gold():
    text = _format_trade_graph_report(
        status={
            "status": "OK",
            "nodes": 7,
            "edges": 4,
            "last_build": {"best_snapshots": 2, "paper_trades": 3, "feedback_labels": 1},
        },
        query={"setups": []},
        symbol="GOLD",
        side="BUY",
        aliases=["GOLD", "XAUUSD"],
        guard={"status": "INSUFFICIENT_DATA", "reason": "no exact graph history"},
        rebuild_interval_seconds=1800,
    )

    assert "AI Finance Agent: Graph RAG memory" in text
    assert "- Nodes/edges: 7 / 4" in text
    assert "- Auto rebuild: every 30 minutes" in text
    assert "- Evidence: 2 /best snapshots, 3 paper trades, 1 feedback labels" in text
    assert "- Query: GOLD BUY | aliases: GOLD, XAUUSD" in text
    assert "- Guard: INSUFFICIENT_DATA | no exact graph history" in text
    assert "Tip: make sure broker symbol alias maps GOLD/XAUUSD correctly" in text


def test_format_trade_graph_report_handles_symbol_without_guard_or_gold_tip():
    text = _format_trade_graph_report(
        status={"status": "OK"},
        query={"setups": []},
        symbol="BTC",
        side="",
        aliases=None,
        guard=None,
        rebuild_interval_seconds=900,
    )

    assert "- Query: BTC | aliases: " in text
    assert "- Guard:" not in text
    assert "broker symbol alias maps GOLD/XAUUSD" not in text


def test_format_trade_graph_report_lists_related_setups():
    text = _format_trade_graph_report(
        status={"status": "OK"},
        query={
            "setups": [
                {
                    "setup": "BTC:BUY",
                    "evaluated_4h": 12,
                    "win_rate_4h": 0.58,
                    "avg_return_4h": 0.012345,
                    "feedback_adjustment": 0.1,
                },
                {
                    "setup": "ETH:SELL",
                    "source": "paper_trades_fallback",
                    "evaluated_4h": 5,
                    "win_rate_4h": 0.4,
                    "avg_return_4h": -12.5,
                    "feedback_adjustment": -0.02,
                },
            ]
        },
        rebuild_interval_seconds=3600,
    )

    assert "Top related setup history:" in text
    assert "- BTC:BUY: eval=12, win_4h=58%, avg=+0.012345, feedback=+0.10" in text
    assert "- ETH:SELL: eval=5, win_4h=40%, avg=-12.50 USD, feedback=-0.02" in text
    assert "- If data is thin, AI should stay in analysis/paper mode." in text


def test_format_why_setup_report_includes_guards_memory_and_nearest_setup():
    text = _format_why_setup_report(
        setup_key="BTC:BUY",
        side="BUY",
        guard={
            "action": "BLOCK_TRADE",
            "status": "BLOCKED",
            "reason": "bad graph history",
            "evaluated_4h": 14,
            "win_rate_4h": 0.25,
            "avg_return_4h": -0.012,
            "blockers": ["low win rate"],
            "warnings": ["thin sample"],
        },
        graph={"setups": [{"setup": "BTC:BUY", "snapshots": 22}]},
        risk_guard={
            "status": "WATCH",
            "opened_trades_today": 2,
            "max_daily_trades": 5,
            "blockers": ["risk cap"],
            "warnings": ["drawdown rising"],
        },
        signal_row={"signals": 7, "evaluated_4h": 4, "win_rate_4h": 0.5},
    )

    assert "Why: BTC:BUY" in text
    assert "- Decision: BLOCK_TRADE (BLOCKED)" in text
    assert "- Graph 4h: eval=14, win=25%, avg=-0.012000" in text
    assert "- Signal memory: signals=7, eval_4h=4, win_4h=50%" in text
    assert "- Daily guard: WATCH | opened=2/5" in text
    assert "- Blockers: low win rate; risk cap" in text
    assert "- Warnings: thin sample; drawdown rising" in text
    assert "- Nearest graph setup: BTC:BUY from 22 records" in text


def test_format_why_setup_report_handles_empty_optional_sections():
    text = _format_why_setup_report(
        setup_key="ETH:SELL",
        side="SELL",
        guard={"action": "ALLOW", "status": "OK", "reason": "fine"},
        graph={},
        risk_guard={},
        signal_row=None,
    )

    assert "Why: ETH:SELL" in text
    assert "- Blockers:" not in text
    assert "- Warnings:" not in text
    assert "- Nearest graph setup:" not in text
    assert "- Signal memory: signals=0, eval_4h=0, win_4h=0%" in text


def test_format_best_alternative_report_includes_best_and_candidates():
    text = _format_best_alternative_report(
        {
            "decision": "TRADE",
            "summary": {"checked": 3, "trade_or_watch": 1, "paper_only": 1, "blocked": 1},
            "risk_guard": {"status": "OK"},
            "best": {
                "symbol": "BTC",
                "side": "BUY",
                "mode": "TRADE_CANDIDATE",
                "reason": "strong graph",
                "guard": {"evaluated_4h": 12, "win_rate_4h": 0.58, "avg_return_4h": 0.01},
                "signal_memory": {"signals": 9, "evaluated_4h": 5},
            },
            "candidates": [
                {
                    "symbol": "BTC",
                    "side": "BUY",
                    "mode": "TRADE_CANDIDATE",
                    "guard": {"evaluated_4h": 12, "win_rate_4h": 0.58, "avg_return_4h": 0.01},
                },
                {
                    "symbol": "ETH",
                    "side": "SELL",
                    "mode": "PAPER_ONLY",
                    "guard": {"evaluated_4h": 1, "win_rate_4h": 0.0, "avg_return_4h": -0.02},
                },
            ],
        }
    )

    assert "AI Finance Agent: Best Alternative" in text
    assert "- Decision: TRADE" in text
    assert "- Checked: 3 setups | trade/watch=1, paper=1, blocked=1" in text
    assert "- Best: BTC BUY | TRADE_CANDIDATE" in text
    assert "- Graph 4h: eval=12, win=58%, avg=+0.010000" in text
    assert "- Signal memory: signals=9, eval_4h=5" in text
    assert "- ETH SELL: PAPER_ONLY | eval=1, win=0%, avg=-0.020000" in text


def test_format_best_alternative_report_handles_no_best():
    text = _format_best_alternative_report(
        {
            "decision": "NO_TRADE",
            "reason": "daily risk guard is blocked",
            "risk_guard": {"status": "BLOCKED"},
            "summary": {},
            "candidates": [],
        }
    )

    assert "- Decision: NO_TRADE" in text
    assert "- Daily guard: BLOCKED" in text
    assert "- Reason: daily risk guard is blocked" in text
    assert "Top candidates:" in text


def test_precheck_open_best_paper_payload_handles_no_trade_and_blocked():
    no_trade = _precheck_open_best_paper_payload({"decision": "NO_TRADE", "reason": "risk cap"})
    empty_best = _precheck_open_best_paper_payload({"decision": "TRADE", "reason": "missing best"})
    blocked = _precheck_open_best_paper_payload(
        {"decision": "TRADE", "best": {"mode": "BLOCK_TRADE", "reason": "bad graph"}}
    )

    assert no_trade["status"] == "NO_TRADE"
    assert no_trade["message"] == "risk cap"
    assert empty_best["status"] == "NO_TRADE"
    assert empty_best["message"] == "missing best"
    assert blocked["status"] == "BLOCKED"
    assert blocked["message"] == "bad graph"


def test_precheck_open_best_paper_payload_validates_symbol_and_side():
    invalid = _precheck_open_best_paper_payload(
        {"decision": "TRADE", "best": {"symbol": "", "side": "HOLD", "mode": "WATCH"}}
    )
    ready = _precheck_open_best_paper_payload(
        {"decision": "WATCH", "best": {"symbol": " btc ", "side": " buy ", "mode": "WATCH"}}
    )

    assert invalid["status"] == "NO_TRADE"
    assert invalid["message"] == "Best alternative is missing a valid symbol or side."
    assert ready["status"] == "READY"
    assert ready["symbol"] == "BTC"
    assert ready["side"] == "BUY"
    assert ready["best"]["mode"] == "WATCH"


def test_resolve_best_paper_volume_uses_precedence_and_minimum():
    def num(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    assert _resolve_best_paper_volume(requested_volume="0.2", profile={"default_lot": 0.1}, auto_status={"volume": 0.05}, num_fn=num) == 0.2
    assert _resolve_best_paper_volume(requested_volume=None, profile={"default_lot": "0.03"}, auto_status={"volume": 0.05}, num_fn=num) == 0.03
    assert _resolve_best_paper_volume(requested_volume=None, profile={}, auto_status={"volume": "0.0002"}, num_fn=num) == 0.001
    assert _resolve_best_paper_volume(requested_volume=None, profile={}, auto_status={}, num_fn=num) == 0.01


def test_best_paper_entry_reason_summarizes_graph_and_signal_evidence():
    reason = _best_paper_entry_reason(
        {
            "mode": "PAPER_ONLY",
            "reason": "collect evidence",
            "guard": {"evaluated_4h": 3},
            "signal_memory": {"evaluated_4h": 2},
        }
    )

    assert reason == "BestAlt evidence PAPER_ONLY | graph=collect evidence | eval_4h=3 | signal_eval_4h=2"


def test_format_open_best_paper_result_handles_opened_trade():
    text = _format_open_best_paper_result(
        {
            "status": "OPENED",
            "opened": {"trade_id": 42, "volume": 0.03, "levels_attached": True},
            "setup": {"symbol": "BTC", "side": "BUY", "entry_price": 65000.123456},
            "best_alternative": {"best": {"mode": "WATCH", "reason": "graph acceptable"}},
        },
        num_fn=float,
    )

    assert "Opened best paper evidence trade." in text
    assert "- Paper trade ID: 42" in text
    assert "- Best: BTC BUY | WATCH" in text
    assert "- Volume: 0.03" in text
    assert "- Entry price: 65000.12346" in text
    assert "- SL/TP attached: True" in text
    assert "Mode: paper evidence only, no live order." in text


def test_format_open_best_paper_result_handles_existing_trade():
    text = _format_open_best_paper_result(
        {
            "status": "ALREADY_OPEN",
            "trade": {"id": 7, "symbol": "ETH", "side": "SELL", "status": "OPEN", "entry_price": "123.456789"},
        },
        num_fn=lambda value: float(value or 0),
    )

    assert "Best paper evidence trade already open." in text
    assert "- Paper trade ID: 7" in text
    assert "- Symbol: ETH SELL" in text
    assert "- Entry price: 123.45679" in text


def test_format_open_best_paper_result_handles_cooldown():
    text = _format_open_best_paper_result(
        {
            "status": "COOLDOWN",
            "cooldown_minutes": 30,
            "message": "wait",
            "best_alternative": {"best": {"symbol": "SOL", "side": "BUY", "mode": "PAPER_ONLY"}},
        },
        num_fn=float,
    )

    assert "Best paper evidence trade is cooling down." in text
    assert "- Best: SOL BUY | PAPER_ONLY" in text
    assert "- Wait: 30 minutes" in text
    assert "- Reason: wait" in text


def test_format_open_best_paper_result_handles_fallback_status():
    with_message = _format_open_best_paper_result(
        {"status": "PRICE_UNAVAILABLE", "message": "no quote", "best_alternative": {"best": {"reason": "best reason"}}},
        num_fn=float,
    )
    with_best_reason = _format_open_best_paper_result(
        {"status": "BLOCKED", "best_alternative": {"best": {"reason": "graph blocked"}}},
        num_fn=float,
    )

    assert "- Status: PRICE_UNAVAILABLE" in with_message
    assert "- Reason: no quote" in with_message
    assert "- Status: BLOCKED" in with_best_reason
    assert "- Reason: graph blocked" in with_best_reason


def test_format_open_best_paper_blocked_exception_prefers_guard_details():
    text = _format_open_best_paper_blocked_exception(
        {
            "status": "DETAIL_STATUS",
            "message": "blocked by graph",
            "guard": {"status": "GRAPH_GUARD_BLOCKED", "blockers": ["low win", "bad avg"]},
        },
        status_code=409,
    )

    assert "Best paper trade blocked safely." in text
    assert "- Status: GRAPH_GUARD_BLOCKED" in text
    assert "- Reason: blocked by graph" in text
    assert "- Blockers: low win, bad avg" in text


def test_format_open_best_paper_blocked_exception_handles_plain_detail_and_defaults():
    plain = _format_open_best_paper_blocked_exception("plain failure", status_code=500)
    default_reason = _format_open_best_paper_blocked_exception({"status": "BLOCKED"}, status_code=409)

    assert "- Status: 500" in plain
    assert "- Reason: plain failure" in plain
    assert "- Blockers: none" in plain
    assert "- Status: BLOCKED" in default_reason
    assert "- Reason: risk/graph guard blocked" in default_reason
