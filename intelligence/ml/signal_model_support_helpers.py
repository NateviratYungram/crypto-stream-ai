from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def normalize_paper_symbol(symbol: str) -> str:
    normalized = str(symbol or "").upper().strip()
    if normalized.endswith("USDT"):
        normalized = normalized[:-4] + "USD"
    return normalized


def count_reason(report: Dict[str, Any], reason: str) -> None:
    reasons = report.setdefault("reasons", {})
    reasons[reason] = int(reasons.get(reason, 0) or 0) + 1


def paper_feature_coverage(features: Dict[str, Any], feature_cols: List[str]) -> int:
    covered = 0
    for column in feature_cols:
        if column not in features:
            continue
        try:
            value = float(features.get(column))
        except Exception:
            continue
        if np.isfinite(value):
            covered += 1
    return covered


def paper_label_quality_decision(
    row: Dict[str, Any],
    features: Dict[str, Any],
    *,
    feature_cols: List[str],
    include_sources: set[str],
    min_abs_pnl: float,
    label_gate_fn: Callable[[str, str, str], Dict[str, Any]] | None = None,
    symbol_policy_fn: Callable[..., Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    source = str(row["entry_source"] or "manual_ui").strip() or "manual_ui"
    symbol = normalize_paper_symbol(str(row["symbol"] or ""))
    side = str(row["side"] or "").upper().strip()
    pnl = float(row["pnl_usd"] or 0.0)
    close_reason = str(row["close_reason"] or "").lower().strip()
    feature_coverage = paper_feature_coverage(features, feature_cols)
    reasons: List[str] = []

    if include_sources and source not in include_sources:
        reasons.append("source_not_trainable")
    if feature_coverage < max(8, min(len(feature_cols), 12)):
        reasons.append("feature_coverage_low")
    if close_reason.startswith("time_expiry") and abs(pnl) < min_abs_pnl:
        reasons.append("tiny_timeout_noise")

    try:
        gate = label_gate_fn(symbol, side, source) if label_gate_fn is not None else {"ok": True, "blockers": []}
        if not bool(gate.get("ok", True)):
            reasons.append("performance_gate_blocked")
        policy = (
            symbol_policy_fn(symbol, side, force_refresh=True)
            if symbol_policy_fn is not None
            else {"action": "allow"}
        )
        if str(policy.get("action") or "").lower() == "block":
            reasons.append("policy_blocked")
    except Exception:
        gate = {"ok": True, "blockers": []}
        policy = {"action": "allow"}

    return {
        "include": not reasons,
        "reasons": reasons,
        "symbol": symbol,
        "side": side,
        "entry_source": source,
        "pnl_usd": pnl,
        "feature_coverage": feature_coverage,
        "performance_gate": gate,
        "symbol_policy": policy,
    }


def build_dataset_report(dataset: pd.DataFrame) -> List[Dict[str, Any]]:
    if dataset is None or dataset.empty:
        return []

    required = {"symbol", "timeframe", "label"}
    if not required.issubset(dataset.columns):
        return []

    report_rows: List[Dict[str, Any]] = []
    grouped = dataset.groupby(["symbol", "timeframe"], dropna=False)
    for (symbol, timeframe), frame in grouped:
        labels = pd.to_numeric(frame["label"], errors="coerce").dropna()
        if labels.empty:
            continue
        report_rows.append(
            {
                "symbol": str(symbol),
                "timeframe": str(timeframe),
                "samples": int(len(frame)),
                "wins": int(labels.sum()),
                "losses": int(len(labels) - labels.sum()),
                "win_rate": round(float(labels.mean()), 4),
            }
        )

    report_rows.sort(key=lambda row: (-row["samples"], row["symbol"], row["timeframe"]))
    return report_rows


def build_sufficiency_status(
    dataset: pd.DataFrame,
    outcomes_count: int,
    *,
    core_symbols: List[str],
    targets: Dict[str, Any],
    dataset_report: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    dataset_report = dataset_report or build_dataset_report(dataset)
    present_symbols = sorted({str(row["symbol"]) for row in dataset_report})
    core_covered = [symbol for symbol in core_symbols if symbol in present_symbols]
    training_samples = int(len(dataset)) if dataset is not None else 0

    paper_progress = min(outcomes_count / targets["paper_labels"], 1.0) if targets["paper_labels"] else 1.0
    sample_progress = min(training_samples / targets["training_samples"], 1.0) if targets["training_samples"] else 1.0
    core_progress = min(len(core_covered) / targets["core_symbols"], 1.0) if targets["core_symbols"] else 1.0
    overall_progress = round(float((paper_progress + sample_progress + core_progress) / 3.0), 4)

    return {
        "targets": targets,
        "current": {
            "paper_labels": int(outcomes_count),
            "training_samples": training_samples,
            "core_symbols_covered": len(core_covered),
        },
        "progress": {
            "paper_labels": round(float(paper_progress), 4),
            "training_samples": round(float(sample_progress), 4),
            "core_symbols": round(float(core_progress), 4),
            "overall": overall_progress,
        },
        "core_symbols": {
            "target": core_symbols,
            "covered": core_covered,
            "missing": [symbol for symbol in core_symbols if symbol not in core_covered],
        },
        "ready_for_improvement": bool(
            outcomes_count >= targets["paper_labels"]
            and training_samples >= targets["training_samples"]
            and len(core_covered) >= targets["core_symbols"]
        ),
    }


def prune_weak_slices(
    dataset: pd.DataFrame,
    min_samples: int = 30,
    min_wins: int = 6,
    min_losses: int = 6,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    report = build_dataset_report(dataset)
    if not report:
        return dataset, []

    keep_keys = set()
    pruned: List[Dict[str, Any]] = []
    for row in report:
        if str(row.get("timeframe", "")).lower() == "paper":
            keep_keys.add((str(row["symbol"]), str(row["timeframe"])))
            continue
        enough_samples = row["samples"] >= min_samples
        enough_balance = row["wins"] >= min_wins and row["losses"] >= min_losses
        if enough_samples and enough_balance:
            keep_keys.add((row["symbol"], row["timeframe"]))
        else:
            reasons = []
            if not enough_samples:
                reasons.append(f"samples<{min_samples}")
            if row["wins"] < min_wins:
                reasons.append(f"wins<{min_wins}")
            if row["losses"] < min_losses:
                reasons.append(f"losses<{min_losses}")
            pruned.append({**row, "reason": ", ".join(reasons)})

    if not keep_keys:
        return dataset, pruned

    mask = dataset.apply(
        lambda row: (str(row.get("symbol")), str(row.get("timeframe"))) in keep_keys,
        axis=1,
    )
    return dataset.loc[mask].copy(), pruned


def build_calibration_profile(y_true: np.ndarray, y_prob: np.ndarray, bins: int = 6) -> Dict[str, Any]:
    if len(y_true) == 0 or len(y_true) != len(y_prob):
        return {"available": False}

    order = np.argsort(y_prob)
    sorted_true = y_true[order]
    sorted_prob = y_prob[order]
    edges = np.linspace(0, len(sorted_prob), bins + 1, dtype=int)
    bucket_rows: List[Dict[str, Any]] = []

    for start, end in zip(edges[:-1], edges[1:]):
        if end <= start:
            continue
        p_slice = sorted_prob[start:end]
        y_slice = sorted_true[start:end]
        bucket_rows.append(
            {
                "pred_mean": round(float(np.mean(p_slice)), 4),
                "actual_rate": round(float(np.mean(y_slice)), 4),
                "count": int(len(p_slice)),
            }
        )

    brier = float(np.mean((y_prob - y_true) ** 2))
    ece = float(
        np.mean(
            [abs(bucket["pred_mean"] - bucket["actual_rate"]) * bucket["count"] for bucket in bucket_rows]
        )
        / len(y_prob)
    )
    return {
        "available": True,
        "method": "quantile_bin_empirical_rate",
        "bins": bucket_rows,
        "brier_score": round(brier, 4),
        "ece": round(ece, 4),
    }


def apply_calibration(prob: float, calibration: Dict[str, Any]) -> float:
    if not calibration or not calibration.get("available"):
        return float(np.clip(prob, 0.0, 1.0))

    bins = calibration.get("bins") or []
    if not bins:
        return float(np.clip(prob, 0.0, 1.0))

    pred_means = np.array([float(bucket["pred_mean"]) for bucket in bins], dtype=float)
    actual_rates = np.array([float(bucket["actual_rate"]) for bucket in bins], dtype=float)
    if len(pred_means) == 1:
        return float(np.clip(actual_rates[0], 0.0, 1.0))

    calibrated = float(np.interp(prob, pred_means, actual_rates, left=actual_rates[0], right=actual_rates[-1]))
    return float(np.clip(calibrated, 0.0, 1.0))


def model_promotion_gate(
    acc: float,
    auc: float,
    walk_forward: Dict[str, Any],
    *,
    min_promotion_auc: float,
    min_promotion_accuracy: float,
    accuracy_tolerance: float,
    min_auc_improvement: float,
    max_accuracy_regression: float,
    model_exists: bool,
    load_incumbent: Callable[[], Dict[str, Any] | None],
) -> Dict[str, Any]:
    epsilon = 1e-9
    blockers: List[str] = []
    accuracy_blocker = ""
    if auc < min_promotion_auc:
        blockers.append(f"roc_auc {auc:.4f} < {min_promotion_auc:.4f}")
    if acc < min_promotion_accuracy:
        accuracy_blocker = f"accuracy {acc:.4f} < {min_promotion_accuracy:.4f}"
        blockers.append(accuracy_blocker)

    wf_summary = (walk_forward or {}).get("summary") or {}
    wf_auc = wf_summary.get("avg_roc_auc")
    wf_auc_float = None
    if wf_auc is not None:
        try:
            wf_auc_float = float(wf_auc)
            if wf_auc_float < min_promotion_auc:
                blockers.append(f"walk_forward_auc {wf_auc_float:.4f} < {min_promotion_auc:.4f}")
        except Exception:
            pass

    override_reason = ""
    incumbent_metrics: Dict[str, Any] = {}
    if accuracy_blocker and len(blockers) == 1:
        try:
            incumbent = load_incumbent() or {}
        except Exception:
            incumbent = {}
        incumbent_acc = incumbent.get("accuracy")
        incumbent_auc = incumbent.get("roc_auc")
        incumbent_wf_auc = ((incumbent.get("walk_forward") or {}).get("summary") or {}).get("avg_roc_auc")
        incumbent_metrics = {
            "accuracy": incumbent_acc,
            "roc_auc": incumbent_auc,
            "walk_forward_auc": incumbent_wf_auc,
        }
        try:
            incumbent_acc_float = float(incumbent_acc)
            incumbent_auc_float = float(incumbent_auc)
            incumbent_wf_auc_float = float(incumbent_wf_auc) if incumbent_wf_auc is not None else None
            accuracy_shortfall = min_promotion_accuracy - float(acc)
            auc_improvement = float(auc) - incumbent_auc_float
            accuracy_regression = incumbent_acc_float - float(acc)
            walk_forward_ok = (
                wf_auc_float is None
                or incumbent_wf_auc_float is None
                or wf_auc_float >= min(incumbent_wf_auc_float, min_promotion_auc)
            )
            if (
                accuracy_shortfall <= accuracy_tolerance + epsilon
                and auc_improvement + epsilon >= min_auc_improvement
                and accuracy_regression <= max_accuracy_regression + epsilon
                and walk_forward_ok
            ):
                blockers.remove(accuracy_blocker)
                override_reason = (
                    f"accuracy override: auc improved by {auc_improvement:.4f} vs incumbent while "
                    f"accuracy regression stayed within {max_accuracy_regression:.4f}"
                )
        except Exception:
            pass

    return {
        "promote": not blockers or not model_exists,
        "blockers": blockers,
        "override_reason": override_reason,
        "incumbent_metrics": incumbent_metrics,
        "thresholds": {
            "min_roc_auc": min_promotion_auc,
            "min_accuracy": min_promotion_accuracy,
            "accuracy_tolerance": accuracy_tolerance,
            "min_auc_improvement": min_auc_improvement,
            "max_accuracy_regression": max_accuracy_regression,
        },
    }
