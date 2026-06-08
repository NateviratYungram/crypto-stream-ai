"""Conservative quality gate for user-facing trading signals.

The ML model may produce probabilities before the system has enough live/paper
evidence to trust those probabilities for real-money execution. This module
turns model quality, paper-trade outcomes, and feedback stats into a compact
gate that signal feeds and APIs can expose.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from intelligence.ml.performance_feedback import score_signal_feedback
from intelligence.ml.readiness import ReadinessThresholds, evaluate_readiness
from intelligence.ml.symbol_threshold import get_threshold_for_side

_CACHE_TTL_SECONDS = int(os.getenv("TRADING_GATE_CACHE_TTL_SECONDS", "60"))
_BASE_CACHE: dict[str, Any] = {"loaded_at": 0.0, "report": None, "base": None}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _check_failed(report: dict[str, Any], name: str) -> bool:
    return any(str(item.get("name")) == name and not bool(item.get("ok")) for item in report.get("checks", []))


def _base_gate(force_refresh: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    now = time.time()
    if (
        not force_refresh
        and _BASE_CACHE["report"] is not None
        and _BASE_CACHE["base"] is not None
        and now - float(_BASE_CACHE["loaded_at"] or 0.0) < _CACHE_TTL_SECONDS
    ):
        return _BASE_CACHE["report"], _BASE_CACHE["base"]

    report = evaluate_readiness(require_mt5_audit=False)
    thresholds = ReadinessThresholds()
    model = report.get("model") or {}
    paper = report.get("paper") or {}
    sufficiency = report.get("sufficiency") or {}
    blockers = [str(item.get("name")) for item in report.get("blockers", [])]

    roc_auc = _to_float(model.get("roc_auc"))
    wf_auc = _to_float((model.get("walk_forward") or {}).get("avg_roc_auc"))
    brier = (model.get("calibration") or {}).get("brier_score")
    paper_total = _to_int(paper.get("total"))
    profit_factor = paper.get("profit_factor")
    expectancy = paper.get("expectancy_usd")

    allow_buy_sell = bool(report.get("passed"))
    minimum_buy_sell_probability = 0.56 if allow_buy_sell else 0.66
    minimum_watch_probability = 0.53
    mode = "tradeable" if allow_buy_sell else "observe_only"

    if not allow_buy_sell:
        if (
            model.get("available")
            and _to_int(model.get("n_samples")) >= thresholds.min_model_samples
            and roc_auc >= thresholds.min_holdout_auc
            and wf_auc >= 0.50
        ):
            mode = "paper_only"

        if _check_failed(report, "holdout_auc") or _check_failed(report, "walk_forward_auc"):
            minimum_buy_sell_probability = max(minimum_buy_sell_probability, 0.68)
        if _check_failed(report, "paper_profit_factor") or _check_failed(report, "paper_expectancy"):
            minimum_buy_sell_probability = max(minimum_buy_sell_probability, 0.68)
        if paper_total < thresholds.min_paper_labels:
            minimum_buy_sell_probability = max(minimum_buy_sell_probability, 0.66)

    base = {
        "live_ready": allow_buy_sell,
        "allow_buy_sell": allow_buy_sell,
        "mode": mode,
        "minimum_buy_sell_probability": round(minimum_buy_sell_probability, 4),
        "minimum_watch_probability": round(minimum_watch_probability, 4),
        "blockers": blockers,
        "paper_label_progress": {
            "current": paper_total,
            "target": thresholds.min_paper_labels,
            "ratio": round(min(1.0, paper_total / max(thresholds.min_paper_labels, 1)), 4),
        },
        "model_quality": {
            "available": bool(model.get("available")),
            "roc_auc": model.get("roc_auc"),
            "walk_forward_auc": (model.get("walk_forward") or {}).get("avg_roc_auc"),
            "brier_score": brier,
            "n_samples": model.get("n_samples"),
            "ready_for_improvement": bool(sufficiency.get("ready_for_improvement")),
        },
        "paper_quality": {
            "profit_factor": profit_factor,
            "expectancy_usd": expectancy,
            "win_rate": paper.get("win_rate"),
        },
    }

    _BASE_CACHE["loaded_at"] = now
    _BASE_CACHE["report"] = report
    _BASE_CACHE["base"] = base
    return report, base


def get_trading_quality_gate(
    symbol: Optional[str] = None,
    entry_source: str = "signal_feed_analysis",
    side: Optional[str] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Return a compact gate for signal generation and API display."""
    report, base = _base_gate(force_refresh=force_refresh)
    gate = dict(base)
    gate["blockers"] = list(base.get("blockers", []))

    if symbol:
        feedback = score_signal_feedback(symbol, entry_source=entry_source, side=side)
        source_stats = feedback.get("source_stats") or {}
        symbol_stats = feedback.get("symbol_stats") or {}
        feedback_readiness = feedback.get("readiness") or {}
        adaptive_floor = float(get_threshold_for_side(symbol, side))

        source_trades = _to_int(source_stats.get("trades"))
        symbol_trades = _to_int(symbol_stats.get("trades"))

        readiness_passed = bool(report.get("passed"))

        if source_trades >= 10 and not feedback_readiness.get("source_ready"):
            if readiness_passed:
                # Global readiness confirmed — raise confidence threshold only, don't hard-block
                gate["minimum_buy_sell_probability"] = max(_to_float(gate["minimum_buy_sell_probability"]), 0.68)
            else:
                gate["allow_buy_sell"] = False
                gate["live_ready"] = False
                gate["mode"] = "observe_only"
                gate["minimum_buy_sell_probability"] = max(_to_float(gate["minimum_buy_sell_probability"]), 0.68)
                gate["blockers"].append("performance_source_ready")

        if symbol_trades >= 5 and not feedback_readiness.get("symbol_ready"):
            if readiness_passed:
                # Global readiness confirmed — raise confidence threshold only, don't hard-block
                gate["minimum_buy_sell_probability"] = max(_to_float(gate["minimum_buy_sell_probability"]), 0.68)
            else:
                gate["allow_buy_sell"] = False
                gate["live_ready"] = False
                gate["mode"] = "observe_only"
                gate["minimum_buy_sell_probability"] = max(_to_float(gate["minimum_buy_sell_probability"]), 0.68)
                gate["blockers"].append("performance_symbol_ready")

        gate["minimum_buy_sell_probability"] = max(_to_float(gate["minimum_buy_sell_probability"]), adaptive_floor)

        gate["feedback"] = {
            "symbol": str(symbol).upper(),
            "side": str(side or feedback.get("side") or "").upper(),
            "entry_source": entry_source,
            "notes": feedback.get("notes", []),
            "readiness": feedback_readiness,
            "source_trades": source_trades,
            "symbol_trades": symbol_trades,
            "adaptive_floor": round(adaptive_floor, 4),
        }

    gate["minimum_buy_sell_probability"] = round(_to_float(gate["minimum_buy_sell_probability"]), 4)
    gate["blockers"] = sorted(set(gate.get("blockers", [])))
    gate["readiness_passed"] = bool(report.get("passed"))
    return gate


def clear_trading_quality_gate_cache() -> None:
    _BASE_CACHE["loaded_at"] = 0.0
    _BASE_CACHE["report"] = None
    _BASE_CACHE["base"] = None
