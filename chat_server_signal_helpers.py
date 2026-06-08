from __future__ import annotations


def _telegram_format_signal(symbol: str, setup: dict, graph_guard_fn) -> str:
    if not isinstance(setup, dict) or setup.get("error"):
        error = setup.get("error", "unknown error") if isinstance(setup, dict) else "invalid result"
        return f"Signal error for {symbol}: {error}"

    entry = setup.get("entry_zone") or {}
    edge = setup.get("ai_edge") or {}
    side = str(setup.get("recommendation") or "HOLD").upper()
    graph_guard = graph_guard_fn(symbol, side)
    guard_line = (
        f"- Graph guard: {graph_guard.get('status')} | {graph_guard.get('reason')}\n"
        if side in {"BUY", "SELL"}
        else "- Graph guard: skipped for HOLD/no-direction signal\n"
    )
    return (
        f"Trade plan: {setup.get('symbol', symbol)}\n"
        f"- Signal: {side}\n"
        f"{guard_line}"
        f"- Price: {setup.get('price')}\n"
        f"- Entry: {entry.get('low')} - {entry.get('high')}\n"
        f"- SL: {setup.get('stop_loss')}\n"
        f"- TP1: {setup.get('take_profit_1')}\n"
        f"- TP2: {setup.get('take_profit_2')}\n"
        f"- Confidence: {edge.get('signal_confidence')}\n"
        f"- Win probability: {edge.get('win_pct') or edge.get('win_probability')}\n"
        f"- Note: {setup.get('best_persona', 'Institutional setup')}\n\n"
        + (
            "Graph RAG says do not trade this setup now. Use analysis/paper mode only."
            if graph_guard.get("blockers")
            else "This is analysis only until live quality gates pass."
        )
    )
