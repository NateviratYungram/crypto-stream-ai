#!/usr/bin/env python3
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from intelligence.ml.watchdog import build_watchdog_report, write_watchdog_report

    report = build_watchdog_report()
    path = write_watchdog_report()
    print(json.dumps({"status": "ok", "path": str(path), "healthy": report.get("healthy"), "warnings": report.get("warnings", [])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
