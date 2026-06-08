"""Paper trade scanner and optional auto-retrain loop."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def _scan() -> dict:
    from intelligence.ml.outcome_tracker import scan_and_update
    return scan_and_update()


def _paper_label_count() -> int:
    try:
        from intelligence.ml.outcome_tracker import get_ml_stats
        return int(get_ml_stats().get("total_labeled") or 0)
    except Exception:
        return 0


def _retrain() -> None:
    log.info("Triggering model retrain via train_v8")
    try:
        from intelligence.ml.train_v8 import train

        result = train()
        status = result.get("status", "unknown")
        if status == "trained":
            ensemble = result.get("ensemble") or {}
            neural = result.get("neural") or {}
            log.info(
                "Retrain complete | auc=%s | acc=%s | neural=%s",
                ensemble.get("roc_auc"),
                ensemble.get("accuracy"),
                neural.get("status"),
            )
        elif status == "rejected":
            log.warning(
                "Retrain rejected | blockers=%s",
                (result.get("promotion_gate") or {}).get("blockers", []),
            )
        else:
            log.warning("Retrain finished with status=%s reason=%s", status, result.get("reason"))
    except Exception as exc:
        log.warning("Retrain failed: %s", exc)


def run_once() -> dict:
    result = _scan()
    log.info(
        "Scan done | scanned=%s closed_win=%s closed_loss=%s errors=%s",
        result["scanned"],
        result["closed_win"],
        result["closed_loss"],
        result["errors"],
    )
    labels = _paper_label_count()
    log.info("Paper labels so far: %s/100", labels)
    return result


def run_loop(interval_minutes: int, retrain_every: int) -> None:
    log.info("Scanner loop started | interval=%sm retrain_every=%s labels", interval_minutes, retrain_every)
    labels_since_retrain = 0

    while True:
        try:
            result = run_once()
            new_closed = result["closed_win"] + result["closed_loss"]
            if new_closed > 0:
                labels_since_retrain += new_closed
                log.info(
                    "New labels this cycle: %s (since last retrain: %s)",
                    new_closed,
                    labels_since_retrain,
                )
                if retrain_every > 0 and labels_since_retrain >= retrain_every:
                    _retrain()
                    labels_since_retrain = 0
        except Exception as exc:
            log.error("Scanner cycle error: %s", exc)

        now_utc = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log.info("Next scan in %s min (current UTC: %s)", interval_minutes, now_utc)
        time.sleep(interval_minutes * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan paper trades and auto-close SL/TP hits.")
    parser.add_argument("--loop", type=int, default=0, metavar="MINUTES",
                        help="Run in a loop every N minutes (0 = run once and exit)")
    parser.add_argument("--retrain-every", type=int, default=50, metavar="LABELS",
                        help="Trigger retrain after accumulating N new labels (0 = never)")
    args = parser.parse_args()

    if args.loop > 0:
        run_loop(args.loop, args.retrain_every)
        return 0

    result = run_once()
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
