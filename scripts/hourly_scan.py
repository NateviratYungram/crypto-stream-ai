#!/usr/bin/env python3
"""
Standalone hourly scan — runs without Airflow.

Does everything outcome_scan_dag does:
  1. Scan open paper trades → close any that hit SL/TP
  2. Update adaptive per-symbol confidence thresholds
  3. Clear trading quality gate cache

Schedule via Windows Task Scheduler or cron:
  Windows : schtasks /create /tn "CryptoScan" /tr "python scripts/hourly_scan.py" /sc hourly
  Linux   : echo "0 * * * * cd /path && python scripts/hourly_scan.py" | crontab -
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    os.environ.setdefault("PAPER_TRADE_DB", "data/persistence.db")

    # 1. Scan open trades → close any that hit SL/TP
    try:
        from intelligence.ml.outcome_tracker import scan_and_update
        summary = scan_and_update()
        logger.info(
            f"[Scan] scanned={summary['scanned']} "
            f"closed_win={summary['closed_win']} "
            f"closed_loss={summary['closed_loss']} "
            f"errors={summary['errors']}"
        )
    except Exception as e:
        logger.error(f"[Scan] scan_and_update failed: {e}")

    # 2. Update adaptive thresholds and surface paper-label quality
    try:
        from intelligence.ml.signal_model import get_paper_label_quality_report
        from intelligence.ml.symbol_policy import refresh_symbol_policy_cache
        from intelligence.ml.symbol_threshold import refresh_threshold_cache

        thresholds = refresh_threshold_cache()
        for sym, floor in sorted(thresholds.items()):
            logger.info(f"[Threshold] {sym}: floor={floor:.2f}")
        policy = refresh_symbol_policy_cache()
        logger.info(
            "[Policy] blocked=%s reduced=%s allowed=%s",
            (policy.get("summary") or {}).get("blocked"),
            (policy.get("summary") or {}).get("reduced"),
            (policy.get("summary") or {}).get("allowed"),
        )
        quality = get_paper_label_quality_report(force_refresh=True)
        logger.info(
            "[PaperLabels] included=%s excluded=%s reasons=%s",
            quality.get("included"),
            quality.get("excluded"),
            quality.get("reasons", {}),
        )
    except Exception as e:
        logger.error(f"[Threshold] refresh/report failed: {e}")

    # 3. Clear trading quality gate cache so next signal sees fresh readiness
    try:
        from intelligence.ml.trading_quality_gate import clear_trading_quality_gate_cache
        clear_trading_quality_gate_cache()
        logger.info("[Gate] trading quality gate cache cleared")
    except Exception as e:
        logger.error(f"[Gate] cache clear failed: {e}")

    # 4. Emit ML ops report snapshot for dashboards / scheduled checks
    try:
        from scripts.ml_ops_report import build_report
        report = build_report()
        logger.info(
            "[OpsReport] live_ready=%s blockers=%s blocked_symbol_sides=%s reduced_symbol_sides=%s weak_slices=%s watchdog_healthy=%s",
            report.get("summary", {}).get("live_ready"),
            len(report.get("summary", {}).get("blockers", [])),
            len(report.get("summary", {}).get("blocked_symbol_sides", [])),
            len(report.get("summary", {}).get("reduced_symbol_sides", [])),
            len(report.get("summary", {}).get("weak_slices", [])),
            report.get("summary", {}).get("watchdog_healthy"),
        )
    except Exception as e:
        logger.error(f"[OpsReport] build failed: {e}")

    logger.info("[HourlyScan] complete")


if __name__ == "__main__":
    main()
