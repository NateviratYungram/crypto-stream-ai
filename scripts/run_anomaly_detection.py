"""Run market data anomaly detection once outside Airflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*_args, **_kwargs):
        return False

def _severity_counts(events: list[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for event in events:
        counts[event["severity"]] = counts.get(event["severity"], 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CryptoStream AI anomaly detection once")
    parser.add_argument("--lookback-hours", type=int, default=72)
    parser.add_argument("--max-rows", type=int, default=15_000)
    parser.add_argument("--dry-run", action="store_true", help="Detect but do not persist events")
    parser.add_argument("--print-events", action="store_true", help="Print detected events")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    try:
        from intelligence.ml.anomaly_detection import detect_market_anomalies
        from intelligence.ml.anomaly_store import (
            connect,
            fetch_recent_ohlcv,
            json_default,
            notify_critical_anomalies,
            persist_anomaly_events_with_details,
        )
    except ModuleNotFoundError as exc:
        print(
            f"Missing dependency: {exc.name}. Install project requirements before running anomaly detection.",
            file=sys.stderr,
        )
        return 1

    try:
        conn = connect()
    except Exception as exc:
        print(f"Unable to connect to PostgreSQL: {exc}", file=sys.stderr)
        return 1
    try:
        rows = fetch_recent_ohlcv(
            conn,
            lookback_hours=args.lookback_hours,
            max_rows=args.max_rows,
        )
        events = detect_market_anomalies(rows)
        if args.dry_run:
            inserted = 0
            inserted_events = []
            notified = False
        else:
            inserted, inserted_events = persist_anomaly_events_with_details(conn, events)
            notified = notify_critical_anomalies(inserted_events)

        payload = {
            "rows_scanned": len(rows),
            "events_detected": len(events),
            "events_inserted": inserted,
            "dry_run": args.dry_run,
            "critical_notification_sent": notified,
            "severity_counts": _severity_counts(events),
        }
        print(json.dumps(payload, indent=2, default=json_default))

        if args.print_events:
            print(json.dumps(events, indent=2, default=json_default))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
