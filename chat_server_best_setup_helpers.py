from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


def _safe_num_call(num_fn, value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return num_fn(value)
    except Exception:
        return default


def _parse_percent_like(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, str):
            cleaned = value.replace("%", "").strip()
            parsed = float(cleaned)
            return parsed / 100.0 if parsed > 1.0 else parsed
        parsed = float(value)
        return parsed / 100.0 if parsed > 1.0 else parsed
    except Exception:
        return default


def _best_setup_int_env(name: str, default: int, minimum: int) -> int:
    try:
        return max(int(os.getenv(name, str(default))), minimum)
    except Exception:
        return default


def _best_setup_cache_key(universe: list[str], paper_gate_symbol_fn) -> str:
    cleaned = [paper_gate_symbol_fn(symbol) for symbol in universe if str(symbol).strip()]
    return ",".join(cleaned) or "default"


def _best_setup_entry_decision(item: dict[str, Any], *, graph_guard_fn, num_fn) -> dict[str, Any]:
    graph_guard = graph_guard_fn(item.get("symbol"), item.get("side"))
    if graph_guard.get("blockers"):
        return {
            "action": "WAIT_GRAPH_BLOCKED",
            "reason": "Graph RAG guard blocked this setup: " + graph_guard.get("reason", "weak history"),
            "rr": None,
            "graph_guard": graph_guard,
        }
    side = str(item.get("side") or "").upper()
    price = num_fn(item.get("price"))
    entry = item.get("entry_zone") or {}
    entry_low = num_fn(entry.get("low"))
    entry_high = num_fn(entry.get("high"))
    stop_loss = num_fn(item.get("stop_loss"))
    tp1 = num_fn(item.get("take_profit_1"))
    if not price or not entry_low or not entry_high:
        return {"action": "WAIT", "reason": "entry zone is incomplete", "rr": None}

    entry_mid = (entry_low + entry_high) / 2.0
    risk = abs(entry_mid - stop_loss)
    reward = abs(tp1 - entry_mid)
    rr = round(reward / risk, 2) if risk > 0 else None

    if side == "BUY":
        if entry_low <= price <= entry_high:
            action = "ENTER_NOW"
            reason = "price is inside the planned buy entry zone"
        elif price > entry_high:
            action = "WAIT_PULLBACK"
            reason = "price is above the entry zone; avoid chasing"
        else:
            action = "WAIT_CONFIRM"
            reason = "price is below the entry zone; wait for structure confirmation"
    elif side == "SELL":
        if entry_low <= price <= entry_high:
            action = "ENTER_NOW"
            reason = "price is inside the planned sell entry zone"
        elif price < entry_low:
            action = "WAIT_PULLBACK"
            reason = "price is below the entry zone; avoid chasing"
        else:
            action = "WAIT_CONFIRM"
            reason = "price is above the entry zone; wait for rejection"
    else:
        action = "WAIT"
        reason = "no directional setup"

    if rr is not None and rr < 1.2:
        action = "WAIT_BETTER_RR"
        reason = f"risk/reward is only {rr}R"

    return {"action": action, "reason": reason, "rr": rr, "graph_guard": graph_guard}


def _best_setup_score_explain(
    *,
    confidence: float,
    win_prob: float,
    win_rate: float,
    avg_pnl: float,
    feedback_adjustment: float,
    weights: dict[str, float],
    model_trust: dict[str, Any],
) -> dict[str, Any]:
    pnl_clipped = min(max(float(avg_pnl or 0.0), -1.0), 1.0)
    components = {
        "confidence": round(float(confidence or 0.0) * float(weights.get("confidence", 0.0)), 4),
        "ml_win_probability": round(float(win_prob or 0.0) * float(weights.get("ml_win_probability", 0.0)), 4),
        "paper_win_rate": round(float(win_rate or 0.0) * float(weights.get("paper_win_rate", 0.0)), 4),
        "paper_avg_pnl": round(pnl_clipped * float(weights.get("paper_avg_pnl", 0.0)), 4),
        "human_feedback": round(float(feedback_adjustment or 0.0), 4),
    }
    total = max(sum(components.values()), 0.0)
    return {
        "components": components,
        "total": round(total, 4),
        "model_weighted": bool(model_trust.get("trusted")),
        "model_note": "trusted ML contributes to score"
        if model_trust.get("trusted")
        else "ML is degraded, so ML win probability is not counted",
    }


def _best_setup_risk_summary(
    item: dict[str, Any],
    *,
    num_fn,
    account_summary: dict[str, Any] | None = None,
    chat_id: str | None = None,
    profile_getter=None,
    calculator=None,
) -> dict[str, Any]:
    entry = item.get("entry_zone") or {}
    entry_low = _safe_num_call(num_fn, entry.get("low"))
    entry_high = _safe_num_call(num_fn, entry.get("high"))
    stop_loss = _safe_num_call(num_fn, item.get("stop_loss"))
    if not entry_low or not entry_high or not stop_loss:
        return {"available": False, "reason": "missing entry or stop loss"}

    account = account_summary or {}
    balance = _safe_num_call(num_fn, account.get("balance")) or _safe_num_call(num_fn, account.get("equity")) or 10000.0
    risk_pct = 1.0
    if chat_id and profile_getter:
        try:
            profile_risk = profile_getter(chat_id).get("risk_pct")
            if profile_risk is not None:
                risk_pct = min(max(float(profile_risk), 0.1), 10.0)
        except Exception:
            risk_pct = 1.0

    entry_mid = (entry_low + entry_high) / 2.0
    if not calculator:
        return {
            "available": True,
            "account_balance": round(balance, 2),
            "risk_percent": round(risk_pct, 2),
            "risk_amount": round(balance * risk_pct / 100.0, 2),
            "entry_mid": round(entry_mid, 5),
            "stop_loss": stop_loss,
            "note": "basic risk estimate",
        }

    try:
        result = calculator(
            entry_price=float(entry_mid),
            stop_loss_price=float(stop_loss),
            account_balance_usdt=float(balance),
            risk_percent=float(risk_pct),
            leverage=1.0,
        )
    except Exception as exc:
        return {"available": False, "reason": str(exc)}
    if not isinstance(result, dict) or result.get("error"):
        return {"available": False, "reason": (result or {}).get("error", "risk calculation failed")}
    return {
        "available": True,
        "account_balance": result.get("account_balance_usdt"),
        "risk_percent": result.get("risk_percent"),
        "risk_amount": result.get("risk_usdt"),
        "entry_mid": result.get("entry_price"),
        "stop_loss": result.get("stop_loss_price"),
        "sl_distance_pct": result.get("sl_distance_pct"),
        "position_size_units": result.get("position_size_units"),
        "position_value": result.get("position_value_usdt"),
        "margin_required": result.get("margin_required_usdt"),
        "risk_level": result.get("risk_level"),
        "note": "risk model estimate; for FX/Gold, confirm broker lot conversion before live execution",
    }


def _best_setup_run_id(payload: dict[str, Any], top: dict[str, Any], now_fn=None) -> str:
    now_fn = now_fn or (lambda: datetime.now(timezone.utc).isoformat())
    created = str(payload.get("generated_at") or now_fn())
    minute_bucket = created[:16]
    return f"{minute_bucket}:{top.get('symbol')}:{top.get('side')}:{round(float(top.get('score', 0.0) or 0.0), 3)}"


def _best_outcome_label(row, current_price: float) -> tuple[str, float]:
    entry_price = float(row["price"] or 0.0)
    if entry_price <= 0 or current_price <= 0:
        return "UNKNOWN", 0.0
    side = str(row["side"] or "").upper()
    signed_return = (
        (current_price - entry_price) / entry_price
        if side == "BUY"
        else (entry_price - current_price) / entry_price
    )
    stop_loss = float(row["stop_loss"] or 0.0)
    tp1 = float(row["take_profit_1"] or 0.0)
    if side == "BUY":
        if tp1 > 0 and current_price >= tp1:
            return "TP1", signed_return
        if stop_loss > 0 and current_price <= stop_loss:
            return "SL", signed_return
    elif side == "SELL":
        if tp1 > 0 and current_price <= tp1:
            return "TP1", signed_return
        if stop_loss > 0 and current_price >= stop_loss:
            return "SL", signed_return
    return ("WIN" if signed_return > 0 else "LOSS" if signed_return < 0 else "FLAT", signed_return)


def _best_setup_recommendations(metrics: dict[str, Any]) -> list[str]:
    recommendations = []
    h4 = metrics.get("horizons", {}).get("4h", {})
    if h4.get("evaluated", 0) < 30:
        recommendations.append("Collect at least 30 evaluated /best snapshots before trusting precision claims.")
    elif h4.get("win_rate", 0.0) < 0.5:
        recommendations.append("Keep /best in watch/paper mode; 4h win rate is below 50%.")
    if any(
        value.get("evaluated_4h", 0) >= 5 and value.get("win_rate_4h", 0.0) < 0.4
        for value in metrics.get("by_symbol", {}).values()
    ):
        recommendations.append("Throttle symbols with weak 4h outcome records.")
    return recommendations


def _build_best_setup_metrics(rows, eval_summary: dict[str, Any], horizons) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "available": True,
        "total_snapshots": len(rows),
        "evaluation": eval_summary,
        "horizons": {},
        "by_symbol": {},
        "recent": [],
    }
    for horizon in horizons:
        outcome_key = f"outcome_{horizon}"
        return_key = f"return_{horizon}"
        evaluated = [row for row in rows if row[outcome_key]]
        wins = [row for row in evaluated if row[outcome_key] in {"TP1", "WIN"}]
        losses = [row for row in evaluated if row[outcome_key] in {"SL", "LOSS"}]
        avg_return = sum(float(row[return_key] or 0.0) for row in evaluated) / max(len(evaluated), 1)
        metrics["horizons"][horizon] = {
            "evaluated": len(evaluated),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / max(len(evaluated), 1), 4),
            "avg_return": round(avg_return, 6),
        }

    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(str(row["symbol"] or "UNKNOWN"), []).append(row)
    for symbol, symbol_rows in grouped.items():
        evaluated = [row for row in symbol_rows if row["outcome_4h"]]
        wins = [row for row in evaluated if row["outcome_4h"] in {"TP1", "WIN"}]
        avg_return = sum(float(row["return_4h"] or 0.0) for row in evaluated) / max(len(evaluated), 1)
        metrics["by_symbol"][symbol] = {
            "snapshots": len(symbol_rows),
            "evaluated_4h": len(evaluated),
            "win_rate_4h": round(len(wins) / max(len(evaluated), 1), 4),
            "avg_return_4h": round(avg_return, 6),
        }

    for row in rows[:20]:
        metrics["recent"].append(
            {
                "created_at": row["created_at"],
                "symbol": row["symbol"],
                "side": row["side"],
                "score": row["score"],
                "decision": row["decision_action"],
                "no_trade": bool(row["no_trade"]),
                "outcome_1h": row["outcome_1h"],
                "return_1h": row["return_1h"],
                "outcome_4h": row["outcome_4h"],
                "return_4h": row["return_4h"],
                "outcome_24h": row["outcome_24h"],
                "return_24h": row["return_24h"],
            }
        )
    metrics["recommendations"] = _best_setup_recommendations(metrics)
    return metrics


def _build_trade_memory_document(
    metrics: dict[str, Any],
    feedback: dict[str, Any],
    risk_guard: dict[str, Any],
    *,
    generated_at: str,
) -> str:
    lines = [
        "CryptoStream AI trade memory",
        f"Generated at: {generated_at}",
        "",
        "Best setup outcome metrics:",
    ]
    for horizon, row in (metrics.get("horizons") or {}).items():
        lines.append(
            f"- {horizon}: evaluated={row.get('evaluated', 0)}, wins={row.get('wins', 0)}, "
            f"losses={row.get('losses', 0)}, win_rate={float(row.get('win_rate', 0.0)):.4f}, "
            f"avg_return={float(row.get('avg_return', 0.0)):+.6f}"
        )
    lines.append("")
    lines.append("Symbol 4h records:")
    for symbol, row in sorted((metrics.get("by_symbol") or {}).items())[:30]:
        lines.append(
            f"- {symbol}: snapshots={row.get('snapshots', 0)}, evaluated_4h={row.get('evaluated_4h', 0)}, "
            f"win_rate_4h={float(row.get('win_rate_4h', 0.0)):.4f}, avg_return_4h={float(row.get('avg_return_4h', 0.0)):+.6f}"
        )
    lines.append("")
    lines.append("Telegram setup feedback:")
    lines.append(f"- total_labels={feedback.get('total', 0)} ratings={feedback.get('by_rating', {})}")
    for key, adjustment in sorted((feedback.get('score_adjustments') or {}).items())[:30]:
        lines.append(f"- {key}: score_adjustment={float(adjustment):+.4f}")
    lines.append("")
    lines.append("Daily risk guard:")
    lines.append(
        f"- status={risk_guard.get('status')} pnl_today={risk_guard.get('paper_pnl_usd_today')} "
        f"opened_trades_today={risk_guard.get('opened_trades_today')}/{risk_guard.get('max_daily_trades')} "
        f"open_trades={risk_guard.get('open_trades')}"
    )
    if risk_guard.get("blockers"):
        lines.append(f"- blockers={risk_guard.get('blockers')}")
    lines.append("")
    lines.append("Operational rules learned:")
    lines.append("- Do not claim /best is precise until at least 30 evaluated snapshots exist.")
    lines.append("- If daily risk guard is blocked, do not open new live or paper positions.")
    lines.append("- If ML model is degraded, prioritize tactics, paper edge, and human feedback over ML probability.")
    lines.append("- If Telegram feedback adjustment is strongly negative, pause that symbol/side from top ranking.")
    lines.append("- Treat entry zone alerts as watch triggers; re-check momentum, spread, RR, and risk guard before execution.")
    return "\n".join(lines)


def _daily_risk_guard_summary(
    *,
    balance: float,
    daily_loss_limit_pct: float,
    max_daily_trades: int,
    today: str,
    closed,
    opened,
    open_row,
    chat_id: str | None = None,
) -> dict[str, Any]:
    pnl_usd = float((closed or {})["pnl_usd"] or 0.0)
    opened_count = int((opened or {})["trades"] or 0)
    loss_limit_usd = balance * daily_loss_limit_pct / 100.0
    blockers = []
    warnings = []
    if pnl_usd <= -loss_limit_usd:
        blockers.append(f"daily paper/live-equivalent loss {pnl_usd:.2f} <= -{loss_limit_usd:.2f}")
    elif pnl_usd <= -(loss_limit_usd * 0.75):
        warnings.append("daily loss is near the configured limit")
    if opened_count >= max_daily_trades:
        blockers.append(f"daily trade count {opened_count} >= {max_daily_trades}")
    return {
        "status": "blocked" if blockers else "watch" if warnings else "ok",
        "date": today,
        "balance_basis": round(balance, 2),
        "daily_loss_limit_pct": daily_loss_limit_pct,
        "daily_loss_limit_usd": round(loss_limit_usd, 2),
        "paper_pnl_usd_today": round(pnl_usd, 2),
        "closed_trades_today": int((closed or {})["trades"] or 0),
        "opened_trades_today": opened_count,
        "open_trades": int((open_row or {})["open_trades"] or 0),
        "max_daily_trades": max_daily_trades,
        "blockers": blockers,
        "warnings": warnings,
        "chat_id": str(chat_id) if chat_id else None,
    }


def _build_setup_feedback_summary(rows) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "available": True,
        "total": 0,
        "by_rating": {},
        "by_symbol_side": {},
        "recent": [],
        "score_adjustments": {},
        "recommendations": [],
    }
    rating_weights = {
        "GOOD": 1.0,
        "BAD": -1.0,
        "WRONG": -1.4,
        "LATE": -0.7,
    }
    for row in rows:
        rating = str(row["rating"] or "UNKNOWN").upper()
        symbol = str(row["symbol"] or "NA").upper()
        side = str(row["side"] or "NA").upper()
        key = f"{symbol}:{side}"
        summary["total"] += 1
        summary["by_rating"][rating] = int(summary["by_rating"].get(rating, 0) or 0) + 1
        target = summary["by_symbol_side"].setdefault(
            key,
            {"symbol": symbol, "side": side, "count": 0, "weighted_score": 0.0, "ratings": {}},
        )
        target["count"] += 1
        target["weighted_score"] += float(rating_weights.get(rating, 0.0))
        target["ratings"][rating] = int(target["ratings"].get(rating, 0) or 0) + 1
        if len(summary["recent"]) < 20:
            summary["recent"].append(
                {
                    "symbol": symbol,
                    "side": side,
                    "rating": rating,
                    "source": row["source"],
                    "score": row["score"],
                    "created_at": row["created_at"],
                }
            )

    for key, stats in summary["by_symbol_side"].items():
        count = max(int(stats.get("count", 0) or 0), 1)
        avg = float(stats.get("weighted_score", 0.0) or 0.0) / count
        adjustment = max(min(avg * 0.08, 0.12), -0.18)
        stats["avg_feedback_score"] = round(avg, 4)
        stats["score_adjustment"] = round(adjustment, 4)
        summary["score_adjustments"][key] = round(adjustment, 4)

    weak = [
        stats for stats in summary["by_symbol_side"].values()
        if float(stats.get("score_adjustment", 0.0) or 0.0) < 0
    ]
    weak.sort(key=lambda item: float(item.get("score_adjustment", 0.0) or 0.0))
    strong = [
        stats for stats in summary["by_symbol_side"].values()
        if float(stats.get("score_adjustment", 0.0) or 0.0) > 0
    ]
    strong.sort(key=lambda item: float(item.get("score_adjustment", 0.0) or 0.0), reverse=True)
    if weak:
        summary["recommendations"].append(
            "Downgrade setups with negative human feedback: "
            + ", ".join(f"{item['symbol']} {item['side']}" for item in weak[:5])
        )
    if strong:
        summary["recommendations"].append(
            "User feedback currently favors: "
            + ", ".join(f"{item['symbol']} {item['side']}" for item in strong[:5])
        )
    if not rows:
        summary["recommendations"].append("No Telegram setup feedback yet. Use /best and press Good/Bad/Too late/Wrong direction.")
    return summary


def _telegram_format_feedback(summary: dict[str, Any]) -> str:
    if not summary.get("available"):
        return f"Feedback diagnostics unavailable: {summary.get('error')}"
    lines = [
        "Telegram feedback learning",
        f"- Total labels: {summary.get('total', 0)}",
        f"- Ratings: {summary.get('by_rating', {})}",
    ]
    ranked = sorted(
        (summary.get("by_symbol_side") or {}).values(),
        key=lambda item: float(item.get("score_adjustment", 0.0) or 0.0),
    )
    if ranked:
        lines.append("")
        lines.append("Most downgraded:")
        for item in ranked[:5]:
            lines.append(
                f"- {item['symbol']} {item['side']}: adj={float(item.get('score_adjustment', 0.0)):+.3f}, ratings={item.get('ratings')}"
            )
        lines.append("")
        lines.append("Most favored:")
        for item in list(reversed(ranked))[:5]:
            lines.append(
                f"- {item['symbol']} {item['side']}: adj={float(item.get('score_adjustment', 0.0)):+.3f}, ratings={item.get('ratings')}"
            )
    if summary.get("recent"):
        lines.append("")
        lines.append("Recent:")
        for row in summary["recent"][:8]:
            lines.append(f"- {row['symbol']} {row['side']}: {row['rating']} at {row['created_at']}")
    if summary.get("recommendations"):
        lines.append("")
        lines.extend(summary["recommendations"][:3])
    return "\n".join(lines)


def _trade_memory_sync_skip(last_sync_at, last_result) -> dict[str, Any]:
    return {
        "status": "SKIPPED",
        "reason": "recently_synced",
        "last_sync_at": last_sync_at,
        "last_result": last_result,
    }


def _trade_memory_sync_success(now_epoch: float, now_iso: str, result) -> tuple[dict[str, Any], dict[str, Any]]:
    state_update = {
        "last_sync_epoch": now_epoch,
        "last_sync_at": now_iso,
        "last_result": result,
        "last_error": None,
    }
    response = {"status": "OK", "result": result, "no_extra_embedding_cost": True}
    return state_update, response


def _trade_memory_sync_error(now_epoch: float, now_iso: str, error: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state_update = {
        "last_sync_epoch": now_epoch,
        "last_sync_at": now_iso,
        "last_error": error,
    }
    response = {"status": "ERROR", "error": error, "no_extra_embedding_cost": True}
    return state_update, response


def _pre_graph_rag_readiness_summary(
    metrics: dict[str, Any],
    feedback: dict[str, Any],
    rag_stats: dict[str, Any],
    trade_memory_sync_state: dict[str, Any],
    outcome_eval_state: dict[str, Any],
    trade_graph_state: dict[str, Any],
    *,
    best_outcome_eval_interval_seconds: int,
    trade_memory_sync_interval_seconds: int,
    trade_graph_rebuild_interval_seconds: int,
) -> dict[str, Any]:
    horizons = metrics.get("horizons") or {}
    h4 = horizons.get("4h") or {}
    snapshots = int(metrics.get("total_snapshots", 0) or 0)
    evaluated_4h = int(h4.get("evaluated", 0) or 0)
    feedback_labels = int(feedback.get("total", 0) or 0)
    trade_memory_ok = bool(trade_memory_sync_state.get("last_sync_at"))

    blockers = []
    if snapshots < 100:
        blockers.append(f"need at least 100 /best snapshots before graph extraction; have {snapshots}")
    if evaluated_4h < 30:
        blockers.append(f"need at least 30 evaluated 4h outcomes; have {evaluated_4h}")
    if not trade_memory_ok:
        blockers.append("trade memory has not synced to RAG yet")
    if rag_stats.get("status") == "ERROR":
        blockers.append(f"RAG stats unavailable: {rag_stats.get('error')}")

    recommendations = []
    if blockers:
        recommendations.append("Keep strengthening vector RAG/trade memory before building Graph RAG.")
    if feedback_labels < 30:
        recommendations.append("Collect more Telegram Good/Bad/Wrong/Late feedback labels for cleaner relations later.")
    recommendations.append("Graph RAG next schema should start small: Symbol -> Setup -> Outcome -> Feedback -> MarketRegime.")

    return {
        "ready_for_graph_rag": not blockers,
        "blockers": blockers,
        "recommendations": recommendations,
        "requirements": {
            "min_best_snapshots": 100,
            "min_evaluated_4h_outcomes": 30,
            "min_feedback_labels_recommended": 30,
        },
        "current": {
            "best_snapshots": snapshots,
            "evaluated_1h": int((horizons.get("1h") or {}).get("evaluated", 0) or 0),
            "evaluated_4h": evaluated_4h,
            "evaluated_24h": int((horizons.get("24h") or {}).get("evaluated", 0) or 0),
            "feedback_labels": feedback_labels,
            "trade_memory_last_sync_at": trade_memory_sync_state.get("last_sync_at"),
            "trade_memory_last_result": trade_memory_sync_state.get("last_result"),
            "outcome_evaluator": outcome_eval_state,
            "rag_stats": rag_stats,
        },
        "background_tasks": {
            "best_outcome_eval_interval_seconds": best_outcome_eval_interval_seconds,
            "trade_memory_sync_interval_seconds": trade_memory_sync_interval_seconds,
            "trade_graph_rebuild_interval_seconds": trade_graph_rebuild_interval_seconds,
            "trade_graph_rebuild": trade_graph_state,
        },
    }
