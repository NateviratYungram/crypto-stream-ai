import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any

PAPER_DB = os.getenv("PAPER_TRADE_DB", "persistence.db")
_CACHE_TTL_SECONDS = 60
_feedback_cache: dict[str, Any] = {"loaded_at": 0.0, "payload": None}


@contextmanager
def _connect() -> Any:
    conn = sqlite3.connect(PAPER_DB)
    try:
        yield conn
    finally:
        conn.close()


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").upper().strip()
    if normalized.endswith("USDT"):
        normalized = normalized[:-4]
    return normalized


def _split_symbol_side(symbol: str, side: str | None = None) -> tuple[str, str]:
    raw = str(symbol or "").upper().strip()
    embedded_side = ""
    if ":" in raw:
        raw, embedded_side = raw.split(":", 1)
    resolved_side = str(side or embedded_side or "").upper().strip()
    return _normalize_symbol(raw), resolved_side


def _safe_outcome(row: sqlite3.Row) -> str:
    outcome = str(row["outcome"] or "").upper().strip()
    if outcome in {"WIN", "LOSS"}:
        return outcome
    return "WIN" if float(row["pnl_usd"] or 0.0) >= 0 else "LOSS"


def _build_payload() -> dict[str, Any]:
    strategy_stats: dict[str, dict[str, float]] = {}
    symbol_stats: dict[str, dict[str, float]] = {}
    symbol_side_stats: dict[str, dict[str, float]] = {}

    try:
        with _connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT symbol, side, entry_source, pnl_usd, outcome, closed_at
                FROM paper_trades
                WHERE status = 'CLOSED'
                ORDER BY datetime(COALESCE(closed_at, opened_at)) DESC
                """
            ).fetchall()
    except Exception:
        rows = []

    for row in rows:
        source = str(row["entry_source"] or "manual_ui").strip() or "manual_ui"
        symbol = _normalize_symbol(str(row["symbol"] or ""))
        pnl = float(row["pnl_usd"] or 0.0)
        outcome = _safe_outcome(row)

        source_row = strategy_stats.setdefault(source, {"trades": 0, "wins": 0, "pnl": 0.0})
        source_row["trades"] += 1
        source_row["wins"] += 1 if outcome == "WIN" else 0
        source_row["pnl"] += pnl

        symbol_row = symbol_stats.setdefault(symbol, {"trades": 0, "wins": 0, "pnl": 0.0})
        symbol_row["trades"] += 1
        symbol_row["wins"] += 1 if outcome == "WIN" else 0
        symbol_row["pnl"] += pnl

        side = str(row["side"] if "side" in row.keys() else "").upper().strip()
        symbol_side = f"{symbol}:{side or 'UNKNOWN'}"
        side_row = symbol_side_stats.setdefault(symbol_side, {"trades": 0, "wins": 0, "pnl": 0.0})
        side_row["trades"] += 1
        side_row["wins"] += 1 if outcome == "WIN" else 0
        side_row["pnl"] += pnl

    for collection in (strategy_stats, symbol_stats, symbol_side_stats):
        for stats in collection.values():
            trades = max(int(stats["trades"]), 0)
            stats["win_rate"] = (float(stats["wins"]) / trades) * 100 if trades else 0.0
            stats["avg_pnl"] = float(stats["pnl"]) / trades if trades else 0.0

    recommendations: list[str] = []
    source_rows = [
        {"key": key, **value} for key, value in strategy_stats.items() if int(value.get("trades", 0)) >= 3
    ]
    symbol_rows = [
        {"key": key, **value} for key, value in symbol_stats.items() if int(value.get("trades", 0)) >= 3
    ]
    source_rows.sort(key=lambda row: float(row["pnl"]), reverse=True)
    symbol_rows.sort(key=lambda row: float(row["pnl"]), reverse=True)

    if source_rows:
        best_source = source_rows[0]
        recommendations.append(
            f"Lean into {best_source['key']} while it is paying ({best_source['pnl']:+.2f} USD, {best_source['win_rate']:.1f}% win rate)."
        )
        worst_source = source_rows[-1]
        if worst_source["pnl"] < 0:
            recommendations.append(
                f"Reduce risk on {worst_source['key']} until it stabilizes ({worst_source['pnl']:+.2f} USD, {worst_source['win_rate']:.1f}% win rate)."
            )

    if symbol_rows:
        best_symbol = symbol_rows[0]
        recommendations.append(
            f"Best symbol lately: {best_symbol['key']} ({best_symbol['pnl']:+.2f} USD across {int(best_symbol['trades'])} trades)."
        )
        worst_symbol = symbol_rows[-1]
        if worst_symbol["pnl"] < 0:
            recommendations.append(
                f"Watch {worst_symbol['key']} closely or downgrade conviction ({worst_symbol['pnl']:+.2f} USD across {int(worst_symbol['trades'])} trades)."
            )

    return {
        "strategy": strategy_stats,
        "symbol": symbol_stats,
        "symbol_side": symbol_side_stats,
        "recommendations": recommendations,
    }


def get_feedback_snapshot(force_refresh: bool = False) -> dict[str, Any]:
    now = time.time()
    if (
        not force_refresh
        and _feedback_cache["payload"] is not None
        and now - float(_feedback_cache["loaded_at"] or 0.0) < _CACHE_TTL_SECONDS
    ):
        return _feedback_cache["payload"]

    payload = _build_payload()
    _feedback_cache["loaded_at"] = now
    _feedback_cache["payload"] = payload
    return payload


def score_signal_feedback(
    symbol: str,
    entry_source: str = "signal_feed_analysis",
    side: str | None = None,
) -> dict[str, Any]:
    snapshot = get_feedback_snapshot()
    normalized_symbol, resolved_side = _split_symbol_side(symbol, side)
    source_stats = snapshot.get("strategy", {}).get(entry_source, {})
    symbol_stats = snapshot.get("symbol", {}).get(normalized_symbol, {})
    symbol_side_stats = (
        snapshot.get("symbol_side", {}).get(f"{normalized_symbol}:{resolved_side}", {})
        if resolved_side
        else {}
    )

    probability_adjustment = 0.0
    notes: list[str] = []

    source_trades = int(source_stats.get("trades", 0) or 0)
    source_win_rate = float(source_stats.get("win_rate", 0.0) or 0.0)
    source_pnl = float(source_stats.get("pnl", 0.0) or 0.0)
    if source_trades >= 5:
        if source_win_rate < 45 or source_pnl < 0:
            probability_adjustment -= 0.03
            notes.append(f"source soft-capped ({source_win_rate:.1f}% / {source_pnl:+.2f})")
        elif source_win_rate >= 58 and source_pnl > 0:
            probability_adjustment += 0.015
            notes.append(f"source tailwind ({source_win_rate:.1f}% / {source_pnl:+.2f})")

    symbol_trades = int(symbol_stats.get("trades", 0) or 0)
    symbol_win_rate = float(symbol_stats.get("win_rate", 0.0) or 0.0)
    symbol_pnl = float(symbol_stats.get("pnl", 0.0) or 0.0)
    if symbol_trades >= 3:
        if symbol_win_rate < 45 or symbol_pnl < 0:
            probability_adjustment -= 0.025
            notes.append(f"symbol drag ({symbol_win_rate:.1f}% / {symbol_pnl:+.2f})")
        elif symbol_win_rate >= 60 and symbol_pnl > 0:
            probability_adjustment += 0.02
            notes.append(f"symbol strength ({symbol_win_rate:.1f}% / {symbol_pnl:+.2f})")

    side_trades = int(symbol_side_stats.get("trades", 0) or 0)
    side_win_rate = float(symbol_side_stats.get("win_rate", 0.0) or 0.0)
    side_pnl = float(symbol_side_stats.get("pnl", 0.0) or 0.0)
    if side_trades >= 3:
        if side_win_rate < 45 or side_pnl < 0:
            probability_adjustment -= 0.025
            notes.append(f"symbol-side drag ({side_win_rate:.1f}% / {side_pnl:+.2f})")
        elif side_win_rate >= 60 and side_pnl > 0:
            probability_adjustment += 0.02
            notes.append(f"symbol-side strength ({side_win_rate:.1f}% / {side_pnl:+.2f})")

    readiness = {
        "source_ready": bool(source_trades >= 10 and source_win_rate >= 50 and source_pnl >= 0),
        "symbol_ready": bool(symbol_trades >= 5 and symbol_win_rate >= 50 and symbol_pnl >= 0),
        "symbol_side_ready": bool(side_trades >= 3 and side_win_rate >= 50 and side_pnl >= 0),
        "symbol_side_evaluable": bool(side_trades >= 3),
    }

    return {
        "probability_adjustment": probability_adjustment,
        "notes": notes,
        "symbol": normalized_symbol,
        "side": resolved_side,
        "source_stats": source_stats,
        "symbol_stats": symbol_stats,
        "symbol_side_stats": symbol_side_stats,
        "readiness": readiness,
    }


def paper_entry_performance_gate(symbol: str, side: str, entry_source: str) -> dict[str, Any]:
    """Guard new paper entries using realized paper-trade performance only."""
    return _paper_performance_gate(symbol, side, entry_source, mode="execution")


def paper_training_label_gate(symbol: str, side: str, entry_source: str) -> dict[str, Any]:
    """Decide whether a closed paper trade should feed retraining labels."""
    return _paper_performance_gate(symbol, side, entry_source, mode="training")


def _paper_performance_gate(symbol: str, side: str, entry_source: str, mode: str) -> dict[str, Any]:
    snapshot = get_feedback_snapshot(force_refresh=True)
    normalized_symbol = _normalize_symbol(symbol)
    side = str(side or "").upper().strip()
    source = str(entry_source or "manual_ui").strip() or "manual_ui"
    source_stats = snapshot.get("strategy", {}).get(source, {})
    symbol_stats = snapshot.get("symbol", {}).get(normalized_symbol, {})
    symbol_side_stats = snapshot.get("symbol_side", {}).get(f"{normalized_symbol}:{side}", {})

    blockers: list[str] = []
    warnings: list[str] = []

    def _detail(stats: dict[str, Any], label: str) -> tuple[int, float, float, float, str]:
        trades = int(stats.get("trades", 0) or 0)
        win_rate = float(stats.get("win_rate", 0.0) or 0.0)
        avg_pnl = float(stats.get("avg_pnl", 0.0) or 0.0)
        pnl = float(stats.get("pnl", 0.0) or 0.0)
        detail = f"{label}: trades={trades}, win_rate={win_rate:.1f}%, avg_pnl={avg_pnl:+.4f}, pnl={pnl:+.2f}"
        return trades, win_rate, avg_pnl, pnl, detail

    def _guard_execution(stats: dict[str, Any], label: str, min_trades: int, hard_win_rate: float, hard_avg_pnl: float) -> None:
        trades, win_rate, avg_pnl, pnl, detail = _detail(stats, label)
        if trades < min_trades:
            return
        if (avg_pnl < hard_avg_pnl and pnl < 0) or (win_rate < hard_win_rate and pnl < 0):
            blockers.append(detail)
        elif win_rate < 45.0 or avg_pnl < 0:
            warnings.append(detail)

    def _guard_training(
        stats: dict[str, Any],
        label: str,
        min_trades: int,
        hard_win_rate: float,
        hard_avg_pnl: float,
        hard_total_pnl: float,
    ) -> None:
        trades, win_rate, avg_pnl, pnl, detail = _detail(stats, label)
        if trades < min_trades:
            return
        if win_rate < hard_win_rate and avg_pnl < hard_avg_pnl and pnl < hard_total_pnl:
            blockers.append(detail)
        elif win_rate < 45.0 or avg_pnl < 0 or pnl < 0:
            warnings.append(detail)

    if mode == "training":
        _guard_training(source_stats, f"source {source}", min_trades=12, hard_win_rate=35.0, hard_avg_pnl=-0.10, hard_total_pnl=-1.00)
        _guard_training(symbol_stats, f"symbol {normalized_symbol}", min_trades=5, hard_win_rate=40.0, hard_avg_pnl=-0.10, hard_total_pnl=-0.75)
        _guard_training(symbol_side_stats, f"symbol-side {normalized_symbol} {side}", min_trades=3, hard_win_rate=40.0, hard_avg_pnl=-0.15, hard_total_pnl=-0.75)
    else:
        _guard_execution(source_stats, f"source {source}", min_trades=12, hard_win_rate=35.0, hard_avg_pnl=0.0)
        _guard_execution(symbol_stats, f"symbol {normalized_symbol}", min_trades=5, hard_win_rate=40.0, hard_avg_pnl=0.0)
        _guard_execution(symbol_side_stats, f"symbol-side {normalized_symbol} {side}", min_trades=3, hard_win_rate=40.0, hard_avg_pnl=0.0)

    return {
        "ok": not blockers,
        "mode": mode,
        "blockers": blockers,
        "warnings": warnings,
        "source_stats": source_stats,
        "symbol_stats": symbol_stats,
        "symbol_side_stats": symbol_side_stats,
    }
