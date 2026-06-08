import numpy as np
import pandas as pd

from intelligence.ml.signal_model_support_helpers import (
    apply_calibration,
    build_calibration_profile,
    build_dataset_report,
    build_sufficiency_status,
    count_reason,
    model_promotion_gate,
    normalize_paper_symbol,
    paper_feature_coverage,
    paper_label_quality_decision,
    prune_weak_slices,
)


def test_normalize_symbol_and_reason_counter():
    report = {}
    count_reason(report, "policy_blocked")
    count_reason(report, "policy_blocked")

    assert normalize_paper_symbol("btcusdt") == "BTCUSD"
    assert report["reasons"]["policy_blocked"] == 2


def test_paper_feature_coverage_and_decision_paths():
    features = {"a": 1.0, "b": "2.5", "c": float("nan")}
    coverage = paper_feature_coverage(features, ["a", "b", "c", "d"])

    blocked = paper_label_quality_decision(
        {
            "entry_source": "manual_ui",
            "symbol": "ethusdt",
            "side": "sell",
            "pnl_usd": 0.0,
            "close_reason": "time_expiry_soft",
        },
        features,
        feature_cols=[f"f{i}" for i in range(10)],
        include_sources={"auto_paper"},
        min_abs_pnl=0.1,
        label_gate_fn=lambda symbol, side, source: {"ok": False, "blockers": ["low edge"]},
        symbol_policy_fn=lambda symbol, side, force_refresh=True: {"action": "block"},
    )

    allowed = paper_label_quality_decision(
        {
            "entry_source": "auto_paper",
            "symbol": "btcusd",
            "side": "buy",
            "pnl_usd": 5.0,
            "close_reason": "take_profit",
        },
        {f"f{i}": 1.0 for i in range(12)},
        feature_cols=[f"f{i}" for i in range(12)],
        include_sources={"auto_paper"},
        min_abs_pnl=0.1,
        label_gate_fn=lambda symbol, side, source: {"ok": True, "blockers": []},
        symbol_policy_fn=lambda symbol, side, force_refresh=True: {"action": "allow"},
    )

    assert coverage == 2
    assert blocked["include"] is False
    assert "source_not_trainable" in blocked["reasons"]
    assert "feature_coverage_low" in blocked["reasons"]
    assert "tiny_timeout_noise" in blocked["reasons"]
    assert "performance_gate_blocked" in blocked["reasons"]
    assert "policy_blocked" in blocked["reasons"]
    assert blocked["symbol"] == "ETHUSD"
    assert allowed["include"] is True


def test_dataset_report_sufficiency_and_pruning():
    dataset = pd.DataFrame(
        [
            {"symbol": "BTCUSD", "timeframe": "1h", "label": 1},
            {"symbol": "BTCUSD", "timeframe": "1h", "label": 0},
            {"symbol": "BTCUSD", "timeframe": "1h", "label": 1},
            {"symbol": "ETHUSD", "timeframe": "paper", "label": 1},
            {"symbol": "ETHUSD", "timeframe": "paper", "label": 0},
            {"symbol": "XAUUSD", "timeframe": "4h", "label": 1},
        ]
    )

    report = build_dataset_report(dataset)
    sufficiency = build_sufficiency_status(
        dataset,
        outcomes_count=12,
        core_symbols=["BTCUSD", "ETHUSD", "GOLD"],
        targets={"paper_labels": 10, "training_samples": 6, "core_symbols": 3},
        dataset_report=report,
    )
    pruned_dataset, pruned = prune_weak_slices(dataset, min_samples=3, min_wins=1, min_losses=1)

    assert report[0]["symbol"] == "BTCUSD"
    assert sufficiency["progress"]["paper_labels"] == 1.0
    assert sufficiency["progress"]["training_samples"] == 1.0
    assert sufficiency["current"]["core_symbols_covered"] == 2
    assert sufficiency["ready_for_improvement"] is False
    assert set(pruned_dataset["timeframe"]) == {"1h", "paper"}
    assert any(row["symbol"] == "XAUUSD" for row in pruned)
    assert build_dataset_report(pd.DataFrame()) == []
    assert build_dataset_report(pd.DataFrame([{"symbol": "BTCUSD"}])) == []

    sparse_labels = pd.DataFrame(
        [
            {"symbol": "SOLUSD", "timeframe": "1h", "label": "bad"},
            {"symbol": "SOLUSD", "timeframe": "1h", "label": None},
        ]
    )
    assert build_dataset_report(sparse_labels) == []

    untouched, no_report = prune_weak_slices(pd.DataFrame([{"symbol": "BTCUSD"}]), min_samples=2)
    assert untouched.equals(pd.DataFrame([{"symbol": "BTCUSD"}]))
    assert no_report == []

    mixed_dataset = pd.DataFrame(
        [
            {"symbol": "ADAUSD", "timeframe": "4h", "label": 1},
            {"symbol": "ADAUSD", "timeframe": "4h", "label": 1},
            {"symbol": "ADAUSD", "timeframe": "4h", "label": 1},
            {"symbol": "ADAUSD", "timeframe": "4h", "label": 1},
            {"symbol": "ADAUSD", "timeframe": "4h", "label": 1},
            {"symbol": "ADAUSD", "timeframe": "4h", "label": 0},
        ]
    )
    _filtered, mixed_pruned = prune_weak_slices(mixed_dataset, min_samples=5, min_wins=2, min_losses=2)
    assert mixed_pruned[0]["reason"] == "losses<2"

    wins_only_dataset = pd.DataFrame(
        [
            {"symbol": "DOGEUSD", "timeframe": "1h", "label": 1},
            {"symbol": "DOGEUSD", "timeframe": "1h", "label": 0},
            {"symbol": "DOGEUSD", "timeframe": "1h", "label": 0},
        ]
    )
    _wins_only_filtered, wins_only_pruned = prune_weak_slices(wins_only_dataset, min_samples=5, min_wins=2, min_losses=1)
    assert wins_only_pruned[0]["reason"] == "samples<5, wins<2"

    zero_targets = build_sufficiency_status(
        None,
        outcomes_count=0,
        core_symbols=[],
        targets={"paper_labels": 0, "training_samples": 0, "core_symbols": 0},
        dataset_report=[],
    )
    assert zero_targets["progress"]["overall"] == 1.0
    assert zero_targets["ready_for_improvement"] is True


def test_calibration_helpers_and_promotion_gate():
    y_true = np.array([0, 0, 1, 1, 1, 0], dtype=float)
    y_prob = np.array([0.1, 0.2, 0.55, 0.65, 0.8, 0.9], dtype=float)

    calibration = build_calibration_profile(y_true, y_prob, bins=3)
    calibrated = apply_calibration(0.6, calibration)
    unavailable = build_calibration_profile(np.array([]), np.array([]))
    unchanged = apply_calibration(1.2, {"available": False})

    gate = model_promotion_gate(
        acc=0.3488,
        auc=0.5204,
        walk_forward={"summary": {"avg_roc_auc": 0.507}},
        min_promotion_auc=0.5,
        min_promotion_accuracy=0.35,
        accuracy_tolerance=0.005,
        min_auc_improvement=0.005,
        max_accuracy_regression=0.032,
        model_exists=True,
        load_incumbent=lambda: {
            "accuracy": 0.3788,
            "roc_auc": 0.5117,
            "walk_forward": {"summary": {"avg_roc_auc": 0.505}},
        },
    )
    blocked_gate = model_promotion_gate(
        acc=0.2,
        auc=0.4,
        walk_forward={"summary": {"avg_roc_auc": 0.3}},
        min_promotion_auc=0.5,
        min_promotion_accuracy=0.35,
        accuracy_tolerance=0.005,
        min_auc_improvement=0.005,
        max_accuracy_regression=0.032,
        model_exists=True,
        load_incumbent=lambda: None,
    )

    assert calibration["available"] is True
    assert len(calibration["bins"]) == 3
    assert 0.0 <= calibrated <= 1.0
    assert unavailable == {"available": False}
    assert unchanged == 1.0
    assert gate["promote"] is True
    assert "accuracy override" in gate["override_reason"]
    assert blocked_gate["promote"] is False
    assert any("roc_auc" in blocker for blocker in blocked_gate["blockers"])

    uneven = build_calibration_profile(
        np.array([0.0, 1.0], dtype=float),
        np.array([0.2, 0.8], dtype=float),
        bins=6,
    )
    assert uneven["available"] is True
    assert len(uneven["bins"]) >= 1

    no_override_gate = model_promotion_gate(
        acc=0.34,
        auc=0.52,
        walk_forward={"summary": {"avg_roc_auc": 0.4}},
        min_promotion_auc=0.5,
        min_promotion_accuracy=0.35,
        accuracy_tolerance=0.005,
        min_auc_improvement=0.005,
        max_accuracy_regression=0.032,
        model_exists=True,
        load_incumbent=lambda: {
            "accuracy": 0.35,
            "roc_auc": 0.50,
            "walk_forward": {"summary": {"avg_roc_auc": 0.6}},
        },
    )
    assert no_override_gate["promote"] is False
    assert any("accuracy" in blocker for blocker in no_override_gate["blockers"])

    auc_only_gate = model_promotion_gate(
        acc=0.4,
        auc=0.45,
        walk_forward={},
        min_promotion_auc=0.5,
        min_promotion_accuracy=0.35,
        accuracy_tolerance=0.005,
        min_auc_improvement=0.005,
        max_accuracy_regression=0.032,
        model_exists=True,
        load_incumbent=lambda: None,
    )
    assert auc_only_gate["promote"] is False
    assert auc_only_gate["blockers"] == ["roc_auc 0.4500 < 0.5000"]


def test_helper_fallback_and_edge_paths():
    decision = paper_label_quality_decision(
        {
            "entry_source": "",
            "symbol": "",
            "side": "",
            "pnl_usd": None,
            "close_reason": "",
        },
        {},
        feature_cols=["f0"],
        include_sources=set(),
        min_abs_pnl=0.0,
        label_gate_fn=lambda symbol, side, source: (_ for _ in ()).throw(RuntimeError("boom")),
        symbol_policy_fn=lambda symbol, side, force_refresh=True: {"action": "allow"},
    )
    filtered, pruned = prune_weak_slices(pd.DataFrame([{"symbol": "BTCUSD", "timeframe": "1h", "label": 1}]), min_samples=2)
    no_bins = apply_calibration(0.4, {"available": True, "bins": []})
    single_bin = apply_calibration(0.4, {"available": True, "bins": [{"pred_mean": 0.2, "actual_rate": 0.7}]})
    promote_without_model = model_promotion_gate(
        acc=0.1,
        auc=0.1,
        walk_forward={},
        min_promotion_auc=0.5,
        min_promotion_accuracy=0.35,
        accuracy_tolerance=0.005,
        min_auc_improvement=0.005,
        max_accuracy_regression=0.032,
        model_exists=False,
        load_incumbent=lambda: None,
    )

    assert decision["include"] is False
    assert decision["entry_source"] == "manual_ui"
    assert decision["performance_gate"]["ok"] is True
    assert "feature_coverage_low" in decision["reasons"]
    assert filtered.shape[0] == 1
    assert pruned and pruned[0]["reason"] == "samples<2, wins<6, losses<6"
    assert no_bins == 0.4
    assert single_bin == 0.7
    assert promote_without_model["promote"] is True

    load_error_gate = model_promotion_gate(
        acc=0.34,
        auc=0.52,
        walk_forward={"summary": {"avg_roc_auc": "oops"}},
        min_promotion_auc=0.5,
        min_promotion_accuracy=0.35,
        accuracy_tolerance=0.005,
        min_auc_improvement=0.005,
        max_accuracy_regression=0.032,
        model_exists=True,
        load_incumbent=lambda: (_ for _ in ()).throw(RuntimeError("missing incumbent")),
    )
    assert load_error_gate["promote"] is False
    assert load_error_gate["override_reason"] == ""

    failed_override_gate = model_promotion_gate(
        acc=0.349,
        auc=0.52,
        walk_forward={"summary": {"avg_roc_auc": 0.51}},
        min_promotion_auc=0.5,
        min_promotion_accuracy=0.35,
        accuracy_tolerance=0.005,
        min_auc_improvement=0.02,
        max_accuracy_regression=0.01,
        model_exists=True,
        load_incumbent=lambda: {
            "accuracy": 0.351,
            "roc_auc": 0.519,
            "walk_forward": {"summary": {"avg_roc_auc": 0.52}},
        },
    )
    assert failed_override_gate["promote"] is False
    assert failed_override_gate["override_reason"] == ""
