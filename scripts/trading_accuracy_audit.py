"""Audit whether AI trading signals are ready for stronger execution.

This script is intentionally conservative. It does not optimize parameters or
place trades; it summarizes the evidence we already have: model readiness,
paper-trade outcomes, and quick backtests across a core universe.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from intelligence.backtest_crypto import run_crypto_backtest
from intelligence.ml.readiness import get_model_quality_summary, get_paper_trade_performance
from intelligence.ml.trading_quality_gate import get_trading_quality_gate


DEFAULT_SYMBOLS = ["BTC", "ETH", "GOLD", "EURUSD"]


def _asset_class(symbol: str) -> str:
    return "macro" if symbol.upper() in {"GOLD", "SILVER", "OIL", "EURUSD", "GBPUSD", "USDJPY"} else "crypto"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _audit_backtests(
    symbols: list[str],
    timeframe: str,
    limit: int,
    fee_bps: float,
    slippage_bps: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        result = run_crypto_backtest(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            risk_pct=1.0,
            leverage=1.0,
            asset_class=_asset_class(symbol),
            initial_balance=100.0,
            params={"fee_bps": fee_bps, "slippage_bps": slippage_bps},
        )
        if result.get("status") != "success":
            rows.append({"symbol": symbol, "status": result.get("status", "error"), "error": result.get("error") or result.get("message")})
            continue

        trades = int(result.get("total_trades") or 0)
        profit_factor = result.get("profit_factor")
        expectancy = _safe_float(result.get("expectancy_pct"))
        passed = (
            trades >= 20
            and _safe_float(profit_factor) >= 1.2
            and expectancy > 0
            and _safe_float(result.get("net_return_pct")) > 0
        )
        rows.append(
            {
                "symbol": symbol,
                "status": "success",
                "passed": passed,
                "total_trades": trades,
                "win_rate_pct": result.get("win_rate_pct"),
                "profit_factor": profit_factor,
                "expectancy_pct": result.get("expectancy_pct"),
                "net_return_pct": result.get("net_return_pct"),
                "max_drawdown_pct": result.get("max_drawdown_pct"),
                "cost_model": result.get("cost_model"),
            }
        )
    return rows


def build_audit(
    symbols: list[str],
    timeframe: str,
    limit: int,
    fee_bps: float = 4.0,
    slippage_bps: float = 2.0,
) -> dict[str, Any]:
    gate = get_trading_quality_gate(force_refresh=True)
    model = get_model_quality_summary()
    paper = get_paper_trade_performance()
    backtests = _audit_backtests(
        symbols,
        timeframe=timeframe,
        limit=limit,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    successful = [row for row in backtests if row.get("status") == "success"]
    passed_backtests = [row for row in successful if row.get("passed")]

    ready = bool(gate.get("live_ready")) and len(successful) > 0 and len(passed_backtests) == len(successful)
    blockers: list[str] = list(gate.get("blockers", []))
    if not successful:
        blockers.append("backtest_no_successful_symbols")
    elif len(passed_backtests) < len(successful):
        blockers.append("backtest_thresholds_not_met")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready_for_live_ai_trading": ready,
        "mode": "tradeable" if ready else gate.get("mode", "observe_only"),
        "blockers": sorted(set(blockers)),
        "quality_gate": gate,
        "model": model,
        "paper": paper,
        "backtests": {
            "timeframe": timeframe,
            "limit": limit,
            "cost_model": {
                "fee_bps": fee_bps,
                "slippage_bps": slippage_bps,
            },
            "symbols": symbols,
            "passed_symbols": len(passed_backtests),
            "successful_symbols": len(successful),
            "rows": backtests,
            "thresholds": {
                "min_trades_per_symbol": 20,
                "min_profit_factor": 1.2,
                "min_expectancy_pct": 0.0,
                "min_net_return_pct": 0.0,
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit AI trading signal readiness.")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--fee-bps", type=float, default=4.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    args = parser.parse_args()

    report = build_audit(
        args.symbols,
        timeframe=args.timeframe,
        limit=args.limit,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
    )
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report.get("ready_for_live_ai_trading") else 2


if __name__ == "__main__":
    raise SystemExit(main())
