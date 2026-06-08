from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable


def _trade_graph_key(node_type: str, *parts: Any) -> str:
    clean_parts = [str(part or "UNKNOWN").strip().upper().replace(" ", "_") for part in parts]
    return f"{node_type.lower()}:" + ":".join(clean_parts)


def _setup_node_key(symbol: str, side: str) -> str:
    return _trade_graph_key("SETUP", symbol, side)


def _current_market_regime(macro_cache: dict[str, Any] | None, *, now_fn: Callable[[], str] | None = None) -> dict[str, Any]:
    text = json.dumps(macro_cache or {}, ensure_ascii=False, default=str).upper()
    regime = "NEUTRAL"
    if any(token in text for token in ("RISK_OFF", "FEAR", "BEAR", "DXY_UP", "HIGH_VOL")):
        regime = "RISK_OFF"
    elif any(token in text for token in ("RISK_ON", "GREED", "BULL", "LOW_VOL")):
        regime = "RISK_ON"
    timestamp = now_fn() if now_fn is not None else datetime.now(timezone.utc).isoformat()
    return {
        "regime": regime,
        "source": "global_macro_cache",
        "generated_at": timestamp,
    }


def _signal_snapshot_id(symbol: str, side: str, timeframe: str, source: str, created_at: str) -> str:
    raw = f"{created_at[:16]}:{symbol}:{side}:{timeframe}:{source}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _build_signal_snapshot_record(
    payload: dict[str, Any],
    source: str,
    *,
    timeframe: str = "15m",
    resolve_trade_symbol_fn,
    num_fn,
    parse_percent_like_fn,
    current_market_regime_fn,
    trade_graph_guard_fn,
    now_fn: Callable[[], str] | None = None,
    signal_snapshot_id_fn: Callable[[str, str, str, str, str], str] | None = None,
) -> dict[str, Any]:
    symbol = str(payload.get("symbol") or payload.get("ticker") or "").upper().strip()
    if not symbol:
        return {"status": "SKIPPED", "reason": "missing_symbol"}

    resolved = resolve_trade_symbol_fn(symbol)
    canonical = str(resolved.get("canonical") or symbol).upper()
    side = str(
        payload.get("candidate_direction")
        or payload.get("direction")
        or payload.get("recommendation")
        or "HOLD"
    ).upper().strip()
    if side not in {"BUY", "SELL", "HOLD", "WAIT"}:
        side = "HOLD"

    price = num_fn(payload.get("price") or payload.get("current_price"))
    if not price or price <= 0:
        return {"status": "SKIPPED", "reason": "missing_price", "symbol": canonical, "side": side}

    confidence = parse_percent_like_fn(payload.get("confidence") or payload.get("signal_confidence"), 0.0)
    win_probability = parse_percent_like_fn(
        payload.get("ml_win_prob") or payload.get("win_probability") or payload.get("win_pct"),
        0.0,
    )
    regime = current_market_regime_fn()
    graph_guard = trade_graph_guard_fn(canonical, side) if side in {"BUY", "SELL"} else {"status": "SKIPPED"}
    created_at = now_fn() if now_fn is not None else datetime.now(timezone.utc).isoformat()
    signal_id_builder = signal_snapshot_id_fn or _signal_snapshot_id
    signal_id = signal_id_builder(canonical, side, timeframe, source, created_at)

    return {
        "status": "OK",
        "signal_id": signal_id,
        "symbol": symbol,
        "canonical_symbol": canonical,
        "side": side,
        "timeframe": timeframe,
        "price": float(price),
        "confidence": float(confidence),
        "win_probability": float(win_probability),
        "source": source,
        "market_regime": regime.get("regime"),
        "graph_guard": graph_guard,
        "payload_json": json.dumps(payload, ensure_ascii=False, default=str),
        "graph_guard_json": json.dumps(graph_guard, ensure_ascii=False, default=str),
        "created_at": created_at,
    }


def _signal_outcome_label(row: dict[str, Any], current_price: float) -> tuple[str, float]:
    entry = float(row["price"] or 0.0)
    side = str(row["side"] or "").upper()
    if entry <= 0 or current_price <= 0 or side not in {"BUY", "SELL"}:
        return "UNKNOWN", 0.0
    signed_return = ((current_price - entry) / entry) if side == "BUY" else ((entry - current_price) / entry)
    if signed_return >= 0.003:
        label = "WIN"
    elif signed_return <= -0.003:
        label = "LOSS"
    else:
        label = "FLAT"
    return label, round(signed_return, 6)


def _build_signal_snapshot_metrics(rows, evaluation: dict[str, Any]) -> dict[str, Any]:
    by_setup: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row['canonical_symbol']}:{row['side']}"
        target = by_setup.setdefault(key, {"signals": 0, "evaluated_4h": 0, "wins_4h": 0, "avg_return_sum": 0.0})
        target["signals"] += 1
        if row["outcome_4h"]:
            target["evaluated_4h"] += 1
            if row["outcome_4h"] == "WIN":
                target["wins_4h"] += 1
            target["avg_return_sum"] += float(row["return_4h"] or 0.0)

    for item in by_setup.values():
        evaluated = max(int(item["evaluated_4h"]), 1)
        item["win_rate_4h"] = round(float(item["wins_4h"]) / evaluated, 4)
        item["avg_return_4h"] = round(float(item.pop("avg_return_sum", 0.0)) / evaluated, 6)

    return {
        "status": "OK",
        "evaluation": evaluation,
        "total_signals": len(rows),
        "by_setup": by_setup,
        "recent": [
            {
                "created_at": row["created_at"],
                "symbol": row["canonical_symbol"],
                "side": row["side"],
                "price": row["price"],
                "source": row["source"],
                "market_regime": row["market_regime"],
                "outcome_4h": row["outcome_4h"],
                "return_4h": row["return_4h"],
            }
            for row in rows[:25]
        ],
    }


def _build_trade_graph_guard_result(
    *,
    canonical: str | None,
    original_symbol: str | None = None,
    side_upper: str | None,
    graph: dict[str, Any] | None = None,
    setups: list[dict[str, Any]] | None = None,
    graph_error: Exception | str | None = None,
    min_evaluated: int,
    min_win_rate: float,
    min_avg_return: float,
    quarantine_adjustment: float,
) -> dict[str, Any]:
    canonical_symbol = str(canonical or "").upper().strip()
    side = str(side_upper or "").upper().strip()
    if not canonical_symbol or side not in {"BUY", "SELL"}:
        return {
            "status": "INSUFFICIENT_DATA",
            "allowed": True,
            "action": "ALLOW",
            "reason": "symbol or side is missing",
            "symbol": canonical_symbol or original_symbol,
            "side": side or None,
            "blockers": [],
            "warnings": ["Graph guard could not identify a complete setup."],
        }

    if graph_error is not None:
        error_text = str(graph_error)
        return {
            "status": "ERROR",
            "allowed": True,
            "action": "ALLOW_WITH_CAUTION",
            "reason": f"graph guard unavailable: {error_text}",
            "symbol": canonical_symbol,
            "side": side,
            "blockers": [],
            "warnings": [error_text],
        }

    graph_payload = graph or {}
    setup_rows = setups if setups is not None else graph_payload.get("setups") or []
    if not setup_rows:
        return {
            "status": "INSUFFICIENT_DATA",
            "allowed": True,
            "action": "ALLOW_PAPER_ONLY",
            "reason": "no exact graph history for this setup yet",
            "symbol": canonical_symbol,
            "side": side,
            "blockers": [],
            "warnings": ["Use paper/observe mode until this symbol-side has history."],
            "graph_query": graph_payload.get("query"),
        }

    top = setup_rows[0]
    evaluated = int(top.get("evaluated_4h") or 0)
    win_rate = float(top.get("win_rate_4h") or 0.0)
    avg_return = float(top.get("avg_return_4h") or 0.0)
    feedback_adjustment = float(top.get("feedback_adjustment") or 0.0)
    blockers: list[str] = []
    warnings: list[str] = []
    if evaluated < min_evaluated:
        warnings.append(f"only {evaluated} evaluated graph samples; need {min_evaluated}")
    else:
        if win_rate < min_win_rate:
            blockers.append(f"4h graph win rate {win_rate:.0%} < {min_win_rate:.0%}")
        if avg_return < min_avg_return:
            blockers.append(f"4h graph avg return {avg_return:+.6f} < {min_avg_return:+.6f}")
    if feedback_adjustment <= quarantine_adjustment:
        blockers.append(f"human feedback adjustment {feedback_adjustment:+.2f} <= {quarantine_adjustment:+.2f}")

    status = "BLOCKED" if blockers else "WATCH" if warnings else "OK"
    return {
        "status": status,
        "allowed": not blockers,
        "action": "BLOCK_TRADE" if blockers else "ALLOW_WITH_CAUTION" if warnings else "ALLOW",
        "reason": "; ".join(blockers or warnings or ["graph history is acceptable"]),
        "symbol": canonical_symbol,
        "side": side,
        "setup": top.get("setup"),
        "evaluated_4h": evaluated,
        "win_rate_4h": round(win_rate, 4),
        "avg_return_4h": round(avg_return, 6),
        "feedback_adjustment": round(feedback_adjustment, 4),
        "blockers": blockers,
        "warnings": warnings,
        "thresholds": {
            "min_evaluated": min_evaluated,
            "min_win_rate": min_win_rate,
            "min_avg_return": min_avg_return,
            "quarantine_adjustment": quarantine_adjustment,
        },
        "graph_query": graph_payload.get("query"),
    }


def _build_best_alternative_candidates_payload(
    *,
    profile_symbols: list[str] | None = None,
    signal_metrics: dict[str, Any] | None = None,
    risk_guard: dict[str, Any] | None = None,
    trade_graph_guard_fn,
    canonical_symbol_fn,
    min_evaluated: int,
    default_symbols: list[str] | None = None,
) -> dict[str, Any]:
    base_symbols = profile_symbols or default_symbols or ["BTC", "ETH", "GOLD", "EURUSD", "SOL", "XRP"]
    metrics = signal_metrics or {}
    daily_guard = risk_guard or {}
    seen: set[tuple[str, str]] = set()
    candidates: list[dict[str, Any]] = []

    for raw_symbol in base_symbols:
        symbol = canonical_symbol_fn(raw_symbol)
        for side in ("BUY", "SELL"):
            key = (symbol, side)
            if not symbol or key in seen:
                continue
            seen.add(key)
            guard = trade_graph_guard_fn(symbol, side)
            setup_key = f"{guard.get('symbol') or symbol}:{side}"
            signal_row = (metrics.get("by_setup") or {}).get(setup_key) or {}
            if guard.get("blockers") or daily_guard.get("blockers"):
                mode = "BLOCK_TRADE"
                rank = 0
            elif guard.get("status") == "INSUFFICIENT_DATA" or int(guard.get("evaluated_4h") or 0) < min_evaluated:
                mode = "PAPER_ONLY"
                rank = 2
            elif guard.get("warnings"):
                mode = "WATCH"
                rank = 3
            else:
                mode = "TRADE_CANDIDATE"
                rank = 4
            evidence = int(guard.get("evaluated_4h") or 0) + int(signal_row.get("evaluated_4h") or 0)
            avg_return = float(guard.get("avg_return_4h") or 0.0)
            win_rate = float(guard.get("win_rate_4h") or 0.0)
            score = (rank * 1000) + (win_rate * 100) + (avg_return * 10000) + min(evidence, 200)
            candidates.append(
                {
                    "symbol": guard.get("symbol") or symbol,
                    "side": side,
                    "mode": mode,
                    "score": round(score, 4),
                    "guard": guard,
                    "signal_memory": signal_row,
                    "evidence": evidence,
                    "reason": guard.get("reason"),
                }
            )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    actionable = [item for item in candidates if item["mode"] in {"TRADE_CANDIDATE", "WATCH"}]
    paper = [item for item in candidates if item["mode"] == "PAPER_ONLY"]
    blocked = [item for item in candidates if item["mode"] == "BLOCK_TRADE"]
    if daily_guard.get("blockers"):
        decision = "NO_TRADE"
        best = None
        reason = "daily risk guard is blocked"
    elif actionable:
        best = actionable[0]
        decision = "TRADE" if best["mode"] == "TRADE_CANDIDATE" else "WATCH"
        reason = best.get("reason")
    elif paper:
        best = paper[0]
        decision = "PAPER_ONLY"
        reason = best.get("reason")
    else:
        best = None
        decision = "NO_TRADE"
        reason = "all tested setup directions are blocked by Graph RAG guard"
    return {
        "decision": decision,
        "best": best,
        "reason": reason,
        "risk_guard": daily_guard,
        "candidates": candidates,
        "summary": {
            "trade_or_watch": len(actionable),
            "paper_only": len(paper),
            "blocked": len(blocked),
            "checked": len(candidates),
        },
    }


def _format_trade_graph_report(
    *,
    status: dict[str, Any] | None,
    query: dict[str, Any] | None,
    symbol: str = "",
    side: str = "",
    aliases: list[str] | None = None,
    guard: dict[str, Any] | None = None,
    rebuild_interval_seconds: int,
) -> str:
    graph_status = status or {}
    graph_query = query or {}
    query_symbol = str(symbol or "")
    query_side = str(side or "").upper().strip()
    lines = [
        "AI Finance Agent: Graph RAG memory",
        f"- Status: {graph_status.get('status')}",
        f"- Nodes/edges: {graph_status.get('nodes', 0)} / {graph_status.get('edges', 0)}",
        f"- Auto rebuild: every {rebuild_interval_seconds // 60} minutes",
    ]
    last_build = graph_status.get("last_build") or {}
    if last_build:
        lines.append(
            f"- Evidence: {last_build.get('best_snapshots', 0)} /best snapshots, "
            f"{last_build.get('paper_trades', 0)} paper trades, {last_build.get('feedback_labels', 0)} feedback labels"
        )
    if query_symbol:
        alias_text = ", ".join(aliases or [])
        lines.append(f"- Query: {query_symbol}{(' ' + query_side) if query_side else ''} | aliases: {alias_text}")
        if query_side in {"BUY", "SELL"} and guard is not None:
            lines.append(f"- Guard: {guard.get('status')} | {guard.get('reason')}")
    lines.append("")

    setups = graph_query.get("setups") or []
    if not setups:
        lines.extend(
            [
                "No exact setup history found yet.",
                "Action: keep using paper mode for this symbol until the graph collects enough outcomes.",
            ]
        )
        if query_symbol.upper() == "GOLD":
            lines.append("Tip: make sure broker symbol alias maps GOLD/XAUUSD correctly and let paper scanner collect labels.")
        return "\n".join(lines)

    lines.append("Top related setup history:")
    for item in setups[:5]:
        source = item.get("source") or "best_setup_outcomes"
        avg = float(item.get("avg_return_4h", 0.0) or 0.0)
        avg_label = f"{avg:+.6f}" if source != "paper_trades_fallback" else f"{avg:+.2f} USD"
        lines.append(
            f"- {item.get('setup')}: eval={item.get('evaluated_4h', 0)}, "
            f"win_4h={float(item.get('win_rate_4h', 0.0) or 0.0):.0%}, "
            f"avg={avg_label}, feedback={float(item.get('feedback_adjustment', 0.0) or 0.0):+.2f}"
        )

    lines.extend(
        [
            "",
            "How AI uses this:",
            "- If similar setups lost often, confidence is reduced.",
            "- If feedback is negative, the setup is cooled down.",
            "- If data is thin, AI should stay in analysis/paper mode.",
        ]
    )
    return "\n".join(lines)


def _format_why_setup_report(
    *,
    setup_key: str,
    side: str,
    guard: dict[str, Any] | None,
    graph: dict[str, Any] | None,
    risk_guard: dict[str, Any] | None,
    signal_row: dict[str, Any] | None,
) -> str:
    graph_guard = guard or {}
    daily_guard = risk_guard or {}
    signal = signal_row or {}
    lines = [
        f"Why: {setup_key}",
        f"- Decision: {graph_guard.get('action')} ({graph_guard.get('status')})",
        f"- Graph reason: {graph_guard.get('reason')}",
        f"- Graph 4h: eval={graph_guard.get('evaluated_4h', 0)}, win={float(graph_guard.get('win_rate_4h', 0.0) or 0.0):.0%}, avg={float(graph_guard.get('avg_return_4h', 0.0) or 0.0):+.6f}",
        f"- Signal memory: signals={signal.get('signals', 0)}, eval_4h={signal.get('evaluated_4h', 0)}, win_4h={float(signal.get('win_rate_4h', 0.0) or 0.0):.0%}",
        f"- Daily guard: {daily_guard.get('status')} | opened={daily_guard.get('opened_trades_today')}/{daily_guard.get('max_daily_trades')}",
    ]
    blockers = list(graph_guard.get("blockers") or []) + list(daily_guard.get("blockers") or [])
    warnings = list(graph_guard.get("warnings") or []) + list(daily_guard.get("warnings") or [])
    if blockers:
        lines.append("- Blockers: " + "; ".join(blockers[:5]))
    if warnings:
        lines.append("- Warnings: " + "; ".join(warnings[:5]))
    setups = (graph or {}).get("setups") or []
    if setups:
        best = setups[0]
        lines.append(f"- Nearest graph setup: {best.get('setup')} from {best.get('snapshots', 0)} records")
    lines.extend(
        [
            "",
            "Action:",
            "- BLOCK_TRADE means do not live/paper enter this setup now.",
            "- ALLOW_PAPER_ONLY means collect evidence first.",
            "- ALLOW means graph history is not blocking, but other guards still apply.",
        ]
    )
    return "\n".join(lines)


def _format_best_alternative_report(payload: dict[str, Any] | None) -> str:
    best_payload = payload or {}
    best = best_payload.get("best")
    summary = best_payload.get("summary") or {}
    lines = [
        "AI Finance Agent: Best Alternative",
        f"- Decision: {best_payload.get('decision')}",
        f"- Checked: {summary.get('checked', 0)} setups | trade/watch={summary.get('trade_or_watch', 0)}, paper={summary.get('paper_only', 0)}, blocked={summary.get('blocked', 0)}",
        f"- Daily guard: {best_payload.get('risk_guard', {}).get('status')}",
    ]
    if best:
        guard = best.get("guard") or {}
        signal = best.get("signal_memory") or {}
        lines.extend(
            [
                f"- Best: {best.get('symbol')} {best.get('side')} | {best.get('mode')}",
                f"- Reason: {best.get('reason')}",
                f"- Graph 4h: eval={guard.get('evaluated_4h', 0)}, win={float(guard.get('win_rate_4h', 0.0) or 0.0):.0%}, avg={float(guard.get('avg_return_4h', 0.0) or 0.0):+.6f}",
                f"- Signal memory: signals={signal.get('signals', 0)}, eval_4h={signal.get('evaluated_4h', 0)}",
            ]
        )
    else:
        lines.append(f"- Reason: {best_payload.get('reason')}")

    lines.append("")
    lines.append("Top candidates:")
    for item in (best_payload.get("candidates") or [])[:8]:
        guard = item.get("guard") or {}
        lines.append(
            f"- {item.get('symbol')} {item.get('side')}: {item.get('mode')} | "
            f"eval={guard.get('evaluated_4h', 0)}, win={float(guard.get('win_rate_4h', 0.0) or 0.0):.0%}, "
            f"avg={float(guard.get('avg_return_4h', 0.0) or 0.0):+.6f}"
        )

    lines.extend(
        [
            "",
            "Action:",
            "- TRADE/WATCH: still re-check signal, entry, RR, spread, and risk guard.",
            "- PAPER_ONLY: collect evidence, no live trade.",
            "- BLOCK_TRADE: skip this setup.",
        ]
    )
    return "\n".join(lines)


def _precheck_open_best_paper_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    best_payload = payload or {}
    best = best_payload.get("best") or {}
    if best_payload.get("decision") == "NO_TRADE" or not best:
        return {
            "status": "NO_TRADE",
            "message": best_payload.get("reason") or "No eligible best alternative is available.",
            "best_alternative": best_payload,
        }
    if best.get("mode") == "BLOCK_TRADE":
        return {
            "status": "BLOCKED",
            "message": best.get("reason") or "Best alternative is blocked by Graph RAG guard.",
            "best_alternative": best_payload,
        }

    symbol = str(best.get("symbol") or "").upper().strip()
    side = str(best.get("side") or "").upper().strip()
    if not symbol or side not in {"BUY", "SELL"}:
        return {
            "status": "NO_TRADE",
            "message": "Best alternative is missing a valid symbol or side.",
            "best_alternative": best_payload,
        }
    return {
        "status": "READY",
        "symbol": symbol,
        "side": side,
        "best": best,
        "best_alternative": best_payload,
    }


def _resolve_best_paper_volume(
    *,
    requested_volume: Any = None,
    profile: dict[str, Any] | None = None,
    auto_status: dict[str, Any] | None = None,
    num_fn,
    default: float = 0.01,
    minimum: float = 0.001,
) -> float:
    profile_payload = profile or {}
    auto_payload = auto_status or {}
    configured_volume = (
        num_fn(requested_volume)
        or num_fn(profile_payload.get("default_lot"))
        or num_fn(auto_payload.get("volume"))
        or default
    )
    return max(float(configured_volume), minimum)


def _best_paper_entry_reason(best: dict[str, Any] | None) -> str:
    best_payload = best or {}
    guard = best_payload.get("guard") or {}
    signal = best_payload.get("signal_memory") or {}
    return (
        f"BestAlt evidence {best_payload.get('mode')} | "
        f"graph={best_payload.get('reason')} | "
        f"eval_4h={guard.get('evaluated_4h', 0)} | "
        f"signal_eval_4h={signal.get('evaluated_4h', 0)}"
    )


def _format_open_best_paper_result(result: dict[str, Any] | None, *, num_fn) -> str:
    payload = result or {}
    status = payload.get("status")
    best = (payload.get("best_alternative") or {}).get("best") or {}
    if status == "OPENED":
        opened = payload.get("opened") or {}
        setup = payload.get("setup") or {}
        return (
            "Opened best paper evidence trade.\n"
            f"- Paper trade ID: {opened.get('trade_id')}\n"
            f"- Best: {setup.get('symbol')} {setup.get('side')} | {best.get('mode')}\n"
            f"- Volume: {opened.get('volume') or opened.get('quantity') or 'configured'}\n"
            f"- Entry price: {float(setup.get('entry_price') or 0.0):.5f}\n"
            f"- SL/TP attached: {opened.get('levels_attached')}\n"
            f"- Reason: {best.get('reason')}\n\n"
            "Mode: paper evidence only, no live order."
        )
    if status == "ALREADY_OPEN":
        trade = payload.get("trade") or {}
        return (
            "Best paper evidence trade already open.\n"
            f"- Paper trade ID: {trade.get('id')}\n"
            f"- Symbol: {trade.get('symbol')} {trade.get('side')}\n"
            f"- Status: {trade.get('status')}\n"
            f"- Entry price: {num_fn(trade.get('entry_price')):.5f}"
        )
    if status == "COOLDOWN":
        return (
            "Best paper evidence trade is cooling down.\n"
            f"- Best: {best.get('symbol')} {best.get('side')} | {best.get('mode')}\n"
            f"- Wait: {payload.get('cooldown_minutes')} minutes\n"
            f"- Reason: {payload.get('message')}"
        )
    return (
        "Best paper trade not opened.\n"
        f"- Status: {status}\n"
        f"- Reason: {payload.get('message') or (best.get('reason') if best else payload.get('message'))}"
    )


def _format_open_best_paper_blocked_exception(
    detail: dict[str, Any] | Any,
    *,
    status_code: int | None = None,
) -> str:
    payload = detail if isinstance(detail, dict) else {"message": str(detail)}
    guard = payload.get("guard") or {}
    blockers = guard.get("blockers") or payload.get("blockers") or []
    return (
        "Best paper trade blocked safely.\n"
        f"- Status: {guard.get('status') or payload.get('status') or status_code}\n"
        f"- Reason: {payload.get('message') or payload.get('reason') or 'risk/graph guard blocked'}\n"
        f"- Blockers: {', '.join(map(str, blockers)) if blockers else 'none'}"
    )
