# ML Operations Roadmap

Updated: 2026-05-24

## What shipped

- Training label gate split from execution gate
  - Retraining now keeps useful paper labels while live execution stays conservative.
- Promotion history persistence
  - Every retrain can be written into `ml_promotion_history` for audit and dashboard use.
- Symbol-side policy layer
  - Weak symbol/side slices can now be auto-blocked or size-reduced.
- ML ops reporting
  - `scripts/ml_ops_report.py` emits a structured report snapshot.
- Watchdog reporting
  - `scripts/ml_watchdog.py` writes a stale/health watchdog report for model ops.
- Persisted policy overrides
  - Symbol-side blocks/reductions can now be stored in SQLite, not only env vars.
- Frontend ML panel expansion
  - Readiness blockers, promotion history, and policy highlights are surfaced in the UI.

## Current live blocker

- `paper_profit_factor` remains below the live threshold.

## Immediate next work

1. Improve paper profit factor above the configured threshold.
2. Add policy overrides for the weakest slices if operators want manual control.
3. Expand notifications so retrain and readiness deltas are pushed automatically.
4. Keep collecting paper labels for strong slices such as `ETHUSD BUY`.

## Operational commands

- Generate ML ops report:
  - `python scripts/ml_ops_report.py`
- Run the hourly scan:
  - `python scripts/hourly_scan.py`
- Trigger retrain from the API:
  - `POST /api/ml/retrain`

## Useful APIs

- `/api/ml/stats`
- `/api/ml/readiness-report`
- `/api/ml/policies`
- `/api/ml/promotion-history`
- `/api/ml/ops-report`
- `/api/ml/watchdog`
- `/api/ml/weak-slices`
- `/api/ml/policy-overrides`
- `/api/paper-trades/side-scorecard`
