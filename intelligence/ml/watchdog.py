import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_watchdog_report() -> dict[str, Any]:
    from intelligence.ml.readiness import evaluate_readiness
    from intelligence.ml.reporting import build_promotion_summary
    from intelligence.ml.signal_model import MODEL_PATH

    now = datetime.now(timezone.utc)
    model_age_hours = None
    model_exists = MODEL_PATH.exists()
    if model_exists:
        model_mtime = datetime.fromtimestamp(MODEL_PATH.stat().st_mtime, tz=timezone.utc)
        model_age_hours = (now - model_mtime).total_seconds() / 3600.0

    ops_report_path = Path(os.getenv("ML_OPS_REPORT_DIR", "reports")) / "ml_ops_report.json"
    ops_report_age_hours = None
    if ops_report_path.exists():
        ops_mtime = datetime.fromtimestamp(ops_report_path.stat().st_mtime, tz=timezone.utc)
        ops_report_age_hours = (now - ops_mtime).total_seconds() / 3600.0

    readiness = evaluate_readiness(require_mt5_audit=False)
    promotions = build_promotion_summary(limit=5)
    warnings: list[str] = []
    if model_age_hours is not None and model_age_hours > 72:
        warnings.append(f"model file older than 72h ({model_age_hours:.1f}h)")
    if ops_report_age_hours is not None and ops_report_age_hours > 6:
        warnings.append(f"ops report older than 6h ({ops_report_age_hours:.1f}h)")
    if not readiness.get("passed") and readiness.get("blockers"):
        warnings.append("live readiness still blocked")

    latest = promotions.get("latest") or {}
    return {
        "generated_at": now.isoformat(),
        "healthy": len(warnings) == 0,
        "warnings": warnings,
        "model": {
            "exists": model_exists,
            "age_hours": round(model_age_hours, 2) if model_age_hours is not None else None,
        },
        "ops_report": {
            "exists": ops_report_path.exists(),
            "age_hours": round(ops_report_age_hours, 2) if ops_report_age_hours is not None else None,
            "path": str(ops_report_path),
        },
        "readiness": {
            "passed": readiness.get("passed"),
            "blockers": readiness.get("blockers", []),
        },
        "latest_promotion": {
            "status": latest.get("status"),
            "roc_auc": latest.get("roc_auc"),
            "accuracy": latest.get("accuracy"),
            "walk_forward_auc": latest.get("walk_forward_auc"),
        },
    }


def write_watchdog_report() -> Path:
    report = build_watchdog_report()
    output_dir = Path(os.getenv("ML_OPS_REPORT_DIR", "reports"))
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "ml_watchdog_report.json"
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return target
