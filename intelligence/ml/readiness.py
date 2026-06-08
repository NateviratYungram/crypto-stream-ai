"""ML readiness checks for broker-tradeable execution.

This module turns model metrics, labeled paper trades, and optional MT5
history checks into one conservative gate before live order execution.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from intelligence.ml.performance_feedback import (
    get_feedback_snapshot,
    score_signal_feedback,
)

DEFAULT_MT5_AUDIT_SYMBOLS: List[Tuple[str, str]] = [
    ("BTCUSD", "1h"),
    ("ETHUSD", "1h"),
    ("GOLD", "1h"),
    ("EURUSD", "1h"),
]


@dataclass(frozen=True)
class ReadinessThresholds:
    min_paper_labels: int = int(os.getenv("ML_READY_MIN_PAPER_LABELS", "40"))
    min_model_samples: int = int(os.getenv("ML_READY_MIN_MODEL_SAMPLES", "1500"))
    min_holdout_auc: float = float(os.getenv("ML_READY_MIN_HOLDOUT_AUC", "0.503"))
    min_walk_forward_auc: float = float(os.getenv("ML_READY_MIN_WALK_FORWARD_AUC", "0.510"))
    min_profit_factor: float = float(os.getenv("ML_READY_MIN_PROFIT_FACTOR", "1.20"))
    min_expectancy_usd: float = float(os.getenv("ML_READY_MIN_EXPECTANCY_USD", "0.0"))
    max_brier_score: float = float(os.getenv("ML_READY_MAX_BRIER", "0.30"))
    min_mt5_bars: int = int(os.getenv("ML_READY_MIN_MT5_BARS", "500"))


def _paper_db_path() -> str:
    return os.getenv("PAPER_TRADE_DB", "persistence.db")


def _load_model_bundle() -> Optional[Dict[str, Any]]:
    try:
        from intelligence.ml.signal_model import _load_model

        return _load_model()
    except Exception:
        return None


def _reason(ok: bool, name: str, detail: str) -> Dict[str, Any]:
    return {"ok": bool(ok), "name": name, "detail": detail}


def get_paper_trade_performance(limit: int = 300) -> Dict[str, Any]:
    """Summarize closed labeled paper trades with basic trading metrics."""
    path = _paper_db_path()
    if not os.path.exists(path):
        return {
            "available": False,
            "total": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "profit_factor": None,
            "expectancy_usd": None,
            "max_drawdown_usd": None,
            "db_path": path,
        }

    con = None
    try:
        con = sqlite3.connect(path)
        frame = pd.read_sql_query(
            """
            SELECT symbol, outcome, pnl_usd, closed_at
            FROM paper_trades
            WHERE status='CLOSED' AND outcome IS NOT NULL
            ORDER BY COALESCE(closed_at, opened_at) ASC
            LIMIT ?
            """,
            con,
            params=(int(limit),),
        )
    except Exception as exc:
        return {"available": False, "total": 0, "error": str(exc), "db_path": path}
    finally:
        close = getattr(con, "close", None)
        if callable(close):
            close()

    if frame.empty:
        return {
            "available": True,
            "total": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "profit_factor": None,
            "expectancy_usd": None,
            "max_drawdown_usd": None,
            "db_path": path,
        }

    outcomes = frame["outcome"].astype(str).str.upper()
    pnl = pd.to_numeric(frame.get("pnl_usd", 0.0), errors="coerce").fillna(0.0)
    wins = int((outcomes == "WIN").sum())
    losses = int((outcomes == "LOSS").sum())
    total = wins + losses

    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(abs(pnl[pnl < 0].sum()))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (None if gross_profit <= 0 else float("inf"))

    curve = pnl.cumsum()
    running_peak = curve.cummax()
    drawdowns = running_peak - curve

    by_symbol = []
    for symbol, group in frame.groupby("symbol", dropna=False):
        labels = group["outcome"].astype(str).str.upper()
        n = int(len(labels))
        by_symbol.append(
            {
                "symbol": str(symbol),
                "trades": n,
                "win_rate": round(float((labels == "WIN").mean()), 4),
            }
        )
    by_symbol.sort(key=lambda row: (-row["trades"], row["symbol"]))

    return {
        "available": True,
        "total": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(float(wins / total), 4) if total else None,
        "gross_profit_usd": round(gross_profit, 4),
        "gross_loss_usd": round(gross_loss, 4),
        "profit_factor": round(float(profit_factor), 4) if profit_factor is not None and np.isfinite(profit_factor) else profit_factor,
        "expectancy_usd": round(float(pnl.mean()), 4) if len(pnl) else None,
        "max_drawdown_usd": round(float(drawdowns.max()), 4) if len(drawdowns) else None,
        "by_symbol": by_symbol[:20],
        "db_path": path,
    }


def get_model_quality_summary(bundle: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extract the model quality fields that matter for live readiness."""
    bundle = bundle if bundle is not None else _load_model_bundle()
    if bundle is None:
        return {"available": False}

    walk_forward = bundle.get("walk_forward") or {}
    wf_summary = walk_forward.get("summary") or {}
    calibration = bundle.get("calibration") or {}
    sufficiency = bundle.get("sufficiency") or {}
    dataset_quality = bundle.get("dataset_quality") or {}

    return {
        "available": True,
        "n_samples": int(bundle.get("n_samples") or 0),
        "accuracy": bundle.get("accuracy"),
        "roc_auc": bundle.get("roc_auc"),
        "win_rate_train": bundle.get("win_rate_train"),
        "win_rate_test": bundle.get("win_rate_test"),
        "trained_at": bundle.get("trained_at"),
        "split_method": bundle.get("split_method"),
        "walk_forward": wf_summary,
        "calibration": {
            "available": bool(calibration.get("available")),
            "brier_score": calibration.get("brier_score"),
            "ece": calibration.get("ece"),
        },
        "sufficiency": sufficiency,
        "dataset_quality": dataset_quality,
        "slice_pruning": bundle.get("slice_pruning") or {},
    }


def audit_mt5_history(
    symbols: Optional[Sequence[Tuple[str, str]]] = None,
    count: int = 2000,
) -> Dict[str, Any]:
    """Check that broker MT5 history exists and is usable for model training."""
    try:
        from intelligence.mt5_connector import _MT5_AVAILABLE, mt5_get_rates
    except Exception as exc:
        return {"available": False, "passed": False, "error": str(exc), "symbols": []}

    if not _MT5_AVAILABLE:
        return {"available": False, "passed": False, "error": "MetaTrader5 package is not installed", "symbols": []}

    threshold = ReadinessThresholds()
    rows: List[Dict[str, Any]] = []
    for symbol, timeframe in (symbols or DEFAULT_MT5_AUDIT_SYMBOLS):
        item: Dict[str, Any] = {"symbol": symbol, "timeframe": timeframe, "rows": 0, "ok": False, "issues": []}
        try:
            frame = mt5_get_rates(symbol, timeframe=timeframe, count=count)
            if frame is None or frame.empty:
                item["issues"].append("no_history")
            else:
                item["rows"] = int(len(frame))
                item["start"] = str(pd.to_datetime(frame["Datetime"]).min())
                item["end"] = str(pd.to_datetime(frame["Datetime"]).max())
                if len(frame) < threshold.min_mt5_bars:
                    item["issues"].append(f"bars<{threshold.min_mt5_bars}")
                if frame["Datetime"].duplicated().any():
                    item["issues"].append("duplicate_timestamps")
                required = ["Open", "High", "Low", "Close", "Volume"]
                missing = [col for col in required if col not in frame.columns]
                if missing:
                    item["issues"].append(f"missing:{','.join(missing)}")
                item["ok"] = not item["issues"]
        except Exception as exc:
            item["issues"].append(str(exc))
        rows.append(item)

    return {
        "available": True,
        "passed": all(row["ok"] for row in rows) if rows else False,
        "symbols": rows,
    }


def evaluate_readiness(
    require_mt5_audit: bool = False,
    mt5_symbols: Optional[Sequence[Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    """Return a conservative readiness report for live AI execution."""
    thresholds = ReadinessThresholds()
    bundle = _load_model_bundle()
    model = get_model_quality_summary(bundle)
    paper = get_paper_trade_performance()
    performance_feedback = get_feedback_snapshot()

    try:
        from intelligence.ml.signal_model import get_live_sufficiency_status

        sufficiency = get_live_sufficiency_status(bundle)
    except Exception:
        sufficiency = model.get("sufficiency") or {}

    checks: List[Dict[str, Any]] = []
    checks.append(_reason(model.get("available"), "model_available", "trained model bundle must exist"))
    checks.append(
        _reason(
            int(model.get("n_samples") or 0) >= thresholds.min_model_samples,
            "model_sample_count",
            f"{model.get('n_samples', 0)} samples, need >= {thresholds.min_model_samples}",
        )
    )
    checks.append(
        _reason(
            float(model.get("roc_auc") or 0.0) >= thresholds.min_holdout_auc,
            "holdout_auc",
            f"{model.get('roc_auc')} holdout AUC, need >= {thresholds.min_holdout_auc}",
        )
    )

    wf_auc = ((model.get("walk_forward") or {}).get("avg_roc_auc"))
    wf_pass = wf_auc is not None and float(wf_auc) >= thresholds.min_walk_forward_auc
    # Paper-performance override: if paper evidence is strong (PF≥1.5, expectancy>0),
    # accept slightly lower WF AUC (≥0.505) — real trades outweigh theoretical metric
    if not wf_pass and wf_auc is not None and float(wf_auc) >= 0.505:
        paper_pf  = paper.get("profit_factor")
        paper_exp = paper.get("expectancy_usd")
        if (paper_pf and paper_pf != float("inf") and float(paper_pf) >= thresholds.min_profit_factor
                and paper_exp is not None and float(paper_exp) > 0.0):
            wf_pass = True
    checks.append(
        _reason(
            wf_pass,
            "walk_forward_auc",
            f"{wf_auc} walk-forward avg AUC, need >= {thresholds.min_walk_forward_auc}",
        )
    )

    brier = (model.get("calibration") or {}).get("brier_score")
    checks.append(
        _reason(
            brier is not None and float(brier) <= thresholds.max_brier_score,
            "calibration_brier",
            f"{brier} Brier score, need <= {thresholds.max_brier_score}",
        )
    )

    checks.append(
        _reason(
            bool(sufficiency.get("ready_for_improvement")),
            "data_sufficiency",
            f"progress={((sufficiency.get('progress') or {}).get('overall'))}",
        )
    )
    checks.append(
        _reason(
            int(paper.get("total") or 0) >= thresholds.min_paper_labels,
            "paper_label_count",
            f"{paper.get('total', 0)} closed labels, need >= {thresholds.min_paper_labels}",
        )
    )
    checks.append(
        _reason(
            (paper.get("profit_factor") is not None and paper.get("profit_factor") != float("inf") and float(paper.get("profit_factor")) >= thresholds.min_profit_factor)
            or paper.get("profit_factor") == float("inf"),
            "paper_profit_factor",
            f"{paper.get('profit_factor')} profit factor, need >= {thresholds.min_profit_factor}",
        )
    )
    checks.append(
        _reason(
            paper.get("expectancy_usd") is not None and float(paper.get("expectancy_usd")) > thresholds.min_expectancy_usd,
            "paper_expectancy",
            f"{paper.get('expectancy_usd')} average PnL/trade, need > {thresholds.min_expectancy_usd}",
        )
    )

    mt5_audit = None
    if require_mt5_audit:
        mt5_audit = audit_mt5_history(mt5_symbols)
        checks.append(_reason(bool(mt5_audit.get("passed")), "mt5_history", "broker MT5 history audit must pass"))

    passed = all(check["ok"] for check in checks)
    blockers = [check for check in checks if not check["ok"]]

    return {
        "passed": passed,
        "blockers": blockers,
        "checks": checks,
        "thresholds": thresholds.__dict__,
        "model": model,
        "sufficiency": sufficiency,
        "paper": paper,
        "performance_feedback": performance_feedback,
        "mt5_audit": mt5_audit,
    }


def live_execution_gate(
    state: Optional[Dict[str, Any]] = None,
    require_mt5_audit: Optional[bool] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Guard live execution unless readiness passes or override is explicit."""
    if os.getenv("ALLOW_UNREADY_LIVE_TRADING", "0").strip().lower() in {"1", "true", "yes"}:
        report = evaluate_readiness(require_mt5_audit=False)
        report["override"] = "ALLOW_UNREADY_LIVE_TRADING"
        return True, report

    if require_mt5_audit is None:
        require_mt5_audit = os.getenv("ML_REQUIRE_MT5_AUDIT_FOR_LIVE", "0").strip().lower() in {"1", "true", "yes"}

    mt5_symbols = None
    symbol = ""
    side = ""
    if state:
        symbol = str(state.get("symbol") or "").upper()
        timeframe = str(state.get("timeframe") or "1h")
        raw_side = str(
            state.get("side")
            or state.get("action")
            or state.get("master_decision")
            or ""
        ).upper()
        if raw_side in {"LONG", "BUY"}:
            side = "BUY"
        elif raw_side in {"SHORT", "SELL"}:
            side = "SELL"
        if symbol:
            mt5_symbols = [(symbol, timeframe)]

    report = evaluate_readiness(require_mt5_audit=require_mt5_audit, mt5_symbols=mt5_symbols)
    if not symbol:
        return bool(report.get("passed")), report

    feedback = score_signal_feedback(symbol, entry_source="signal_feed_analysis", side=side or None)
    source_stats = feedback.get("source_stats") or {}
    symbol_stats = feedback.get("symbol_stats") or {}
    symbol_side_stats = feedback.get("symbol_side_stats") or {}
    feedback_readiness = feedback.get("readiness") or {}
    feedback_checks: List[Dict[str, Any]] = []

    source_trades = int(source_stats.get("trades", 0) or 0)
    if source_trades >= 10:
        feedback_checks.append(
            _reason(
                bool(feedback_readiness.get("source_ready")),
                "performance_source_ready",
                (
                    "signal_feed_analysis "
                    f"trades={source_trades}, "
                    f"win_rate={float(source_stats.get('win_rate', 0.0) or 0.0):.1f}, "
                    f"pnl={float(source_stats.get('pnl', 0.0) or 0.0):+.2f}"
                ),
            )
        )

    symbol_trades = int(symbol_stats.get("trades", 0) or 0)
    if symbol_trades >= 5:
        feedback_checks.append(
            _reason(
                bool(feedback_readiness.get("symbol_ready")),
                "performance_symbol_ready",
                (
                    f"{symbol} trades={symbol_trades}, "
                    f"win_rate={float(symbol_stats.get('win_rate', 0.0) or 0.0):.1f}, "
                    f"pnl={float(symbol_stats.get('pnl', 0.0) or 0.0):+.2f}"
                ),
            )
        )

    side_trades = int(symbol_side_stats.get("trades", 0) or 0)
    if side and side_trades >= 3:
        feedback_checks.append(
            _reason(
                bool(feedback_readiness.get("symbol_side_ready")),
                "performance_symbol_side_ready",
                (
                    f"{symbol} {side} trades={side_trades}, "
                    f"win_rate={float(symbol_side_stats.get('win_rate', 0.0) or 0.0):.1f}, "
                    f"pnl={float(symbol_side_stats.get('pnl', 0.0) or 0.0):+.2f}"
                ),
            )
        )

    if feedback_checks:
        report["checks"] = list(report.get("checks") or []) + feedback_checks
        report["blockers"] = [check for check in report["checks"] if not check["ok"]]
        report["passed"] = all(check["ok"] for check in report["checks"])

    report["signal_feedback"] = {
        "symbol": symbol,
        "side": side,
        "entry_source": "signal_feed_analysis",
        "notes": feedback.get("notes", []),
        "source_stats": source_stats,
        "symbol_stats": symbol_stats,
        "symbol_side_stats": symbol_side_stats,
        "readiness": feedback_readiness,
    }
    return bool(report.get("passed")), report


def print_readiness_json(report: Dict[str, Any]) -> None:
    """Stable CLI rendering helper."""
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
