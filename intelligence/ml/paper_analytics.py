import os
import sqlite3
from contextlib import closing
from typing import Any

PAPER_DB = os.getenv("PAPER_TRADE_DB", "persistence.db")


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").upper().strip()
    if normalized.endswith("USDT"):
        normalized = normalized[:-4]
    return normalized


def _bucket_metrics(rows: list[sqlite3.Row], key_builder) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = key_builder(row)
        bucket = buckets.setdefault(key, {"key": key, "trades": 0, "wins": 0, "gross_win": 0.0, "gross_loss": 0.0, "net_pnl": 0.0})
        pnl = float(row["pnl_usd"] or 0.0)
        outcome = str(row["outcome"] or ("WIN" if pnl > 0 else "LOSS")).upper()
        bucket["trades"] += 1
        bucket["net_pnl"] += pnl
        if outcome == "WIN":
            bucket["wins"] += 1
            bucket["gross_win"] += max(pnl, 0.0)
        else:
            bucket["gross_loss"] += abs(min(pnl, 0.0))

    results: list[dict[str, Any]] = []
    for bucket in buckets.values():
        trades = max(int(bucket["trades"]), 1)
        gross_loss = float(bucket["gross_loss"])
        gross_win = float(bucket["gross_win"])
        profit_factor = gross_win / gross_loss if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
        results.append(
            {
                **bucket,
                "win_rate": round(float(bucket["wins"]) / trades, 4),
                "avg_pnl": round(float(bucket["net_pnl"]) / trades, 6),
                "profit_factor": round(profit_factor, 6),
                "expectancy_usd": round(float(bucket["net_pnl"]) / trades, 6),
            }
        )
    results.sort(key=lambda item: (float(item["net_pnl"]), float(item["profit_factor"])), reverse=True)
    return results


def build_side_scorecard(limit: int = 50) -> dict[str, Any]:
    try:
        with closing(sqlite3.connect(PAPER_DB)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT symbol, side, entry_source, pnl_usd, outcome, closed_at, opened_at
                FROM paper_trades
                WHERE status = 'CLOSED'
                ORDER BY datetime(COALESCE(closed_at, opened_at)) DESC
                """
            ).fetchall()
    except Exception as exc:
        return {"available": False, "error": str(exc), "side": [], "symbol_side": [], "source_side": [], "weak_slices": []}

    side_rows = _bucket_metrics(rows, lambda row: str(row["side"] or "").upper().strip() or "UNKNOWN")
    symbol_side_rows = _bucket_metrics(rows, lambda row: f"{_normalize_symbol(row['symbol'])}:{str(row['side'] or '').upper().strip() or 'UNKNOWN'}")
    source_side_rows = _bucket_metrics(rows, lambda row: f"{str(row['entry_source'] or 'manual_ui').strip() or 'manual_ui'}:{str(row['side'] or '').upper().strip() or 'UNKNOWN'}")

    weak_slices = [
        row
        for row in symbol_side_rows
        if int(row.get("trades", 0) or 0) >= 3 and (float(row.get("net_pnl", 0.0) or 0.0) < 0 or float(row.get("profit_factor", 0.0) or 0.0) < 1.0)
    ]
    weak_slices.sort(key=lambda item: (float(item.get("net_pnl", 0.0) or 0.0), float(item.get("profit_factor", 0.0) or 0.0)))

    return {
        "available": True,
        "side": side_rows[:limit],
        "symbol_side": symbol_side_rows[:limit],
        "source_side": source_side_rows[:limit],
        "weak_slices": weak_slices[:limit],
    }
