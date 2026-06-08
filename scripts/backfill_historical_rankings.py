import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from intelligence.tools.market_tools import refresh_historical_stock_rankings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill and persist stock historical ranking summaries for 1Y/3Y/5Y/10Y style queries."
    )
    parser.add_argument(
        "--years",
        default="1,3,5,10",
        help="Comma-separated holding periods to refresh, for example: 1,3,5,10",
    )
    parser.add_argument(
        "--allow-partial-window",
        action="store_true",
        help="Include stocks without near-full history across the requested window.",
    )
    args = parser.parse_args()

    years = []
    for item in str(args.years or "").split(","):
        item = item.strip()
        if not item:
            continue
        years.append(int(item))

    result = refresh_historical_stock_rankings(
        years_list=years or [1, 3, 5, 10],
        full_window_only=not args.allow_partial_window,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
