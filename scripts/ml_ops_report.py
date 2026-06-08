#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_report() -> dict:
    from intelligence.ml.performance_feedback import get_feedback_snapshot
    from intelligence.ml.paper_analytics import build_side_scorecard
    from intelligence.ml.readiness import evaluate_readiness
    from intelligence.ml.reporting import build_promotion_summary
    from intelligence.ml.signal_model import get_paper_label_quality_report
    from intelligence.ml.symbol_policy import get_symbol_policy_snapshot
    from intelligence.ml.watchdog import build_watchdog_report

    readiness = evaluate_readiness(require_mt5_audit=False)
    promotions = build_promotion_summary(limit=10)
    paper_quality = get_paper_label_quality_report(force_refresh=True)
    feedback = get_feedback_snapshot(force_refresh=True)
    policies = get_symbol_policy_snapshot(force_refresh=True)
    side_analytics = build_side_scorecard(limit=20)
    watchdog = build_watchdog_report()

    weak_sides = [row for row in policies.get("rows", []) if row.get("action") == "block"]
    reduced_sides = [row for row in policies.get("rows", []) if row.get("action") == "reduce"]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "readiness": readiness,
        "paper_label_quality": paper_quality,
        "promotion_history": promotions,
        "symbol_policy": policies,
        "side_analytics": side_analytics,
        "performance_feedback": feedback,
        "watchdog": watchdog,
        "summary": {
            "live_ready": bool(readiness.get("passed")),
            "blockers": readiness.get("blockers", []),
            "blocked_symbol_sides": weak_sides[:10],
            "reduced_symbol_sides": reduced_sides[:10],
            "weak_slices": side_analytics.get("weak_slices", [])[:10],
            "watchdog_healthy": bool(watchdog.get("healthy")),
        },
    }


def main() -> int:
    report = build_report()
    output_dir = Path(os.getenv("ML_OPS_REPORT_DIR", "reports"))
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "ml_ops_report.json"
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"status": "ok", "path": str(target), "generated_at": report["generated_at"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
