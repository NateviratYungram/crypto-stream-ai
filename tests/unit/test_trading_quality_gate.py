from intelligence.ml import trading_quality_gate as tqg


def test_helper_converters_and_failed_check_detection():
    assert tqg._to_float("1.25") == 1.25
    assert tqg._to_float(None, default=2.5) == 2.5
    assert tqg._to_float("bad", default=3.5) == 3.5
    assert tqg._to_int("7") == 7
    assert tqg._to_int(None, default=4) == 4
    assert tqg._to_int("bad", default=5) == 5
    assert tqg._check_failed({"checks": [{"name": "holdout_auc", "ok": False}]}, "holdout_auc") is True
    assert tqg._check_failed({"checks": [{"name": "holdout_auc", "ok": True}]}, "holdout_auc") is False


def test_gate_raises_min_probability_for_side_floor(monkeypatch):
    monkeypatch.setattr(
        tqg,
        "_base_gate",
        lambda force_refresh=False: (
            {"passed": False, "checks": []},
            {
                "live_ready": False,
                "allow_buy_sell": False,
                "mode": "paper_only",
                "minimum_buy_sell_probability": 0.66,
                "minimum_watch_probability": 0.53,
                "blockers": [],
                "paper_label_progress": {},
                "model_quality": {},
                "paper_quality": {},
            },
        ),
    )
    monkeypatch.setattr(
        tqg,
        "score_signal_feedback",
        lambda symbol, entry_source="signal_feed_analysis", side=None: {
            "notes": [],
            "readiness": {"source_ready": True, "symbol_ready": True},
            "source_stats": {"trades": 0},
            "symbol_stats": {"trades": 0},
            "side": side,
        },
    )
    monkeypatch.setattr(tqg, "get_threshold_for_side", lambda symbol, side=None: 0.7)

    gate = tqg.get_trading_quality_gate("BTCUSD", side="SELL", force_refresh=True)

    assert gate["minimum_buy_sell_probability"] == 0.7
    assert gate["feedback"]["adaptive_floor"] == 0.7


def test_base_gate_uses_cache_and_observe_only_defaults(monkeypatch):
    calls = {"count": 0}
    monkeypatch.setattr(
        tqg,
        "evaluate_readiness",
        lambda require_mt5_audit=False: calls.__setitem__("count", calls["count"] + 1) or {
            "passed": False,
            "checks": [],
            "blockers": [],
            "model": {
                "available": False,
                "roc_auc": 0.4,
                "n_samples": 100,
                "walk_forward": {"avg_roc_auc": 0.45},
                "calibration": {"brier_score": 0.3},
            },
            "paper": {
                "total": 10,
                "profit_factor": 0.8,
                "expectancy_usd": -1.0,
                "win_rate": 0.4,
            },
            "sufficiency": {"ready_for_improvement": False},
        },
    )
    monkeypatch.setattr(
        tqg,
        "ReadinessThresholds",
        lambda: type(
            "Thresholds",
            (),
            {"min_model_samples": 1500, "min_holdout_auc": 0.55, "min_paper_labels": 40},
        )(),
    )
    monkeypatch.setattr(tqg.time, "time", lambda: 100.0)
    tqg.clear_trading_quality_gate_cache()

    report1, base1 = tqg._base_gate(force_refresh=True)
    monkeypatch.setattr(tqg.time, "time", lambda: 120.0)
    report2, base2 = tqg._base_gate(force_refresh=False)

    assert calls["count"] == 1
    assert report1 == report2
    assert base1 == base2
    assert base1["mode"] == "observe_only"
    assert base1["minimum_buy_sell_probability"] == 0.66


def test_base_gate_raises_floor_for_failed_auc_and_paper_checks(monkeypatch):
    monkeypatch.setattr(
        tqg,
        "evaluate_readiness",
        lambda require_mt5_audit=False: {
            "passed": False,
            "checks": [
                {"name": "holdout_auc", "ok": False},
                {"name": "paper_profit_factor", "ok": False},
            ],
            "blockers": [{"name": "holdout_auc"}, {"name": "paper_profit_factor"}],
            "model": {
                "available": False,
                "roc_auc": 0.4,
                "n_samples": 100,
                "walk_forward": {"avg_roc_auc": 0.45},
                "calibration": {"brier_score": 0.3},
            },
            "paper": {
                "total": 10,
                "profit_factor": 0.8,
                "expectancy_usd": -1.0,
                "win_rate": 0.4,
            },
            "sufficiency": {"ready_for_improvement": False},
        },
    )
    monkeypatch.setattr(
        tqg,
        "ReadinessThresholds",
        lambda: type(
            "Thresholds",
            (),
            {"min_model_samples": 1500, "min_holdout_auc": 0.55, "min_paper_labels": 40},
        )(),
    )
    tqg.clear_trading_quality_gate_cache()

    _report, base = tqg._base_gate(force_refresh=True)

    assert base["mode"] == "observe_only"
    assert base["minimum_buy_sell_probability"] == 0.68


def test_base_gate_stays_tradeable_when_readiness_passes(monkeypatch):
    monkeypatch.setattr(
        tqg,
        "evaluate_readiness",
        lambda require_mt5_audit=False: {
            "passed": True,
            "checks": [],
            "blockers": [],
            "model": {
                "available": True,
                "roc_auc": 0.7,
                "n_samples": 4000,
                "walk_forward": {"avg_roc_auc": 0.65},
                "calibration": {"brier_score": 0.1},
            },
            "paper": {
                "total": 80,
                "profit_factor": 1.8,
                "expectancy_usd": 2.0,
                "win_rate": 0.6,
            },
            "sufficiency": {"ready_for_improvement": True},
        },
    )
    monkeypatch.setattr(
        tqg,
        "ReadinessThresholds",
        lambda: type(
            "Thresholds",
            (),
            {"min_model_samples": 1500, "min_holdout_auc": 0.55, "min_paper_labels": 40},
        )(),
    )
    tqg.clear_trading_quality_gate_cache()

    report, base = tqg._base_gate(force_refresh=True)

    assert report["passed"] is True
    assert base["mode"] == "tradeable"
    assert base["minimum_buy_sell_probability"] == 0.56


def test_base_gate_preserves_floor_when_paper_labels_already_sufficient(monkeypatch):
    monkeypatch.setattr(
        tqg,
        "evaluate_readiness",
        lambda require_mt5_audit=False: {
            "passed": False,
            "checks": [],
            "blockers": [],
            "model": {
                "available": False,
                "roc_auc": 0.4,
                "n_samples": 100,
                "walk_forward": {"avg_roc_auc": 0.45},
                "calibration": {"brier_score": 0.3},
            },
            "paper": {
                "total": 80,
                "profit_factor": 1.1,
                "expectancy_usd": 0.2,
                "win_rate": 0.5,
            },
            "sufficiency": {"ready_for_improvement": False},
        },
    )
    monkeypatch.setattr(
        tqg,
        "ReadinessThresholds",
        lambda: type(
            "Thresholds",
            (),
            {"min_model_samples": 1500, "min_holdout_auc": 0.55, "min_paper_labels": 40},
        )(),
    )
    tqg.clear_trading_quality_gate_cache()

    _report, base = tqg._base_gate(force_refresh=True)

    assert base["mode"] == "observe_only"
    assert base["minimum_buy_sell_probability"] == 0.66


def test_base_gate_promotes_to_paper_only_when_model_quality_is_good(monkeypatch):
    monkeypatch.setattr(
        tqg,
        "evaluate_readiness",
        lambda require_mt5_audit=False: {
            "passed": False,
            "checks": [],
            "blockers": [{"name": "paper_label_count"}],
            "model": {
                "available": True,
                "roc_auc": 0.61,
                "n_samples": 2500,
                "walk_forward": {"avg_roc_auc": 0.58},
                "calibration": {"brier_score": 0.18},
            },
            "paper": {
                "total": 30,
                "profit_factor": 1.4,
                "expectancy_usd": 4.2,
                "win_rate": 0.55,
            },
            "sufficiency": {"ready_for_improvement": True},
        },
    )
    monkeypatch.setattr(
        tqg,
        "ReadinessThresholds",
        lambda: type(
            "Thresholds",
            (),
            {"min_model_samples": 1500, "min_holdout_auc": 0.55, "min_paper_labels": 40},
        )(),
    )
    tqg.clear_trading_quality_gate_cache()

    report, base = tqg._base_gate(force_refresh=True)

    assert report["passed"] is False
    assert base["mode"] == "paper_only"
    assert base["allow_buy_sell"] is False
    assert base["paper_label_progress"]["ratio"] == 0.75
    assert base["model_quality"]["ready_for_improvement"] is True


def test_gate_keeps_buy_sell_allowed_when_global_readiness_passes(monkeypatch):
    monkeypatch.setattr(
        tqg,
        "_base_gate",
        lambda force_refresh=False: (
            {"passed": True, "checks": []},
            {
                "live_ready": True,
                "allow_buy_sell": True,
                "mode": "tradeable",
                "minimum_buy_sell_probability": 0.56,
                "minimum_watch_probability": 0.53,
                "blockers": [],
                "paper_label_progress": {},
                "model_quality": {},
                "paper_quality": {},
            },
        ),
    )
    monkeypatch.setattr(
        tqg,
        "score_signal_feedback",
        lambda symbol, entry_source="signal_feed_analysis", side=None: {
            "notes": ["source still noisy"],
            "readiness": {"source_ready": False, "symbol_ready": False},
            "source_stats": {"trades": 12},
            "symbol_stats": {"trades": 6},
            "side": side,
        },
    )
    monkeypatch.setattr(tqg, "get_threshold_for_side", lambda symbol, side=None: 0.62)

    gate = tqg.get_trading_quality_gate("BTCUSD", side="BUY", force_refresh=True)

    assert gate["allow_buy_sell"] is True
    assert gate["live_ready"] is True
    assert gate["mode"] == "tradeable"
    assert gate["minimum_buy_sell_probability"] == 0.68
    assert gate["blockers"] == []


def test_gate_blocks_when_feedback_is_not_ready_and_global_readiness_fails(monkeypatch):
    monkeypatch.setattr(
        tqg,
        "_base_gate",
        lambda force_refresh=False: (
            {"passed": False, "checks": []},
            {
                "live_ready": False,
                "allow_buy_sell": False,
                "mode": "paper_only",
                "minimum_buy_sell_probability": 0.66,
                "minimum_watch_probability": 0.53,
                "blockers": ["paper_label_count"],
                "paper_label_progress": {},
                "model_quality": {},
                "paper_quality": {},
            },
        ),
    )
    monkeypatch.setattr(
        tqg,
        "score_signal_feedback",
        lambda symbol, entry_source="signal_feed_analysis", side=None: {
            "notes": ["symbol and source underperforming"],
            "readiness": {"source_ready": False, "symbol_ready": False},
            "source_stats": {"trades": 20},
            "symbol_stats": {"trades": 8},
            "side": side,
        },
    )
    monkeypatch.setattr(tqg, "get_threshold_for_side", lambda symbol, side=None: 0.64)

    gate = tqg.get_trading_quality_gate("ETHUSD", side="SELL", force_refresh=True)

    assert gate["allow_buy_sell"] is False
    assert gate["live_ready"] is False
    assert gate["mode"] == "observe_only"
    assert gate["minimum_buy_sell_probability"] == 0.68
    assert gate["blockers"] == [
        "paper_label_count",
        "performance_source_ready",
        "performance_symbol_ready",
    ]


def test_gate_without_symbol_returns_base_gate(monkeypatch):
    monkeypatch.setattr(
        tqg,
        "_base_gate",
        lambda force_refresh=False: (
            {"passed": False, "checks": []},
            {
                "live_ready": False,
                "allow_buy_sell": False,
                "mode": "observe_only",
                "minimum_buy_sell_probability": 0.66,
                "minimum_watch_probability": 0.53,
                "blockers": ["paper_label_count"],
                "paper_label_progress": {},
                "model_quality": {},
                "paper_quality": {},
            },
        ),
    )

    gate = tqg.get_trading_quality_gate(force_refresh=True)

    assert gate["minimum_buy_sell_probability"] == 0.66
    assert gate["blockers"] == ["paper_label_count"]
    assert gate["readiness_passed"] is False
    assert "feedback" not in gate
