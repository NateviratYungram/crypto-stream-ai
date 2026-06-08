from __future__ import annotations

from typing import Any, Callable


def _telegram_format_mt5_snapshot(account_cache: dict[str, Any]) -> str:
    account = account_cache.get("summary") or {}
    positions = account_cache.get("positions") or []
    if not account:
        return "MT5 is not synced yet. Check bridge and account poller."
    lines = [
        "MT5 account",
        f"- Connected: {bool(account_cache.get('connected'))}",
        f"- Account: {account.get('login')} ({account.get('company', 'broker')})",
        f"- Balance: {account.get('balance')} {account.get('currency', 'USD')}",
        f"- Equity: {account.get('equity')} {account.get('currency', 'USD')}",
        f"- Open positions: {len(positions)}",
        f"- Trade allowed: {account.get('trade_allowed')}",
        f"- Expert allowed: {account.get('trade_expert')}",
    ]
    for pos in positions[:5]:
        lines.append(f"  {pos.get('symbol')} {pos.get('type')} vol={pos.get('volume')} pnl={pos.get('profit')}")
    return "\n".join(lines)


def _telegram_format_paper_dashboard(
    *,
    gate: dict[str, Any],
    status: dict[str, Any],
    snapshot: dict[str, Any],
    feedback: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    num_fn: Callable[[Any], float],
) -> str:
    summary = snapshot.get("summary") or {}
    progress = gate.get("paper_label_progress") or {}
    label_current = progress.get("current", summary.get("label_count", 0))
    label_target = progress.get("target", summary.get("label_target", 100))
    remaining = max(int(label_target or 0) - int(label_current or 0), 0)
    profit_factor = summary.get("profit_factor")
    profit_factor_text = "inf" if profit_factor == 999.0 else (f"{profit_factor:.2f}x" if profit_factor else "n/a")
    open_lines = []
    for trade in (snapshot.get("open_trades") or [])[:4]:
        open_lines.append(
            f"  {trade.get('symbol')} {trade.get('side')} vol={trade.get('volume')} "
            f"entry={num_fn(trade.get('entry_price')):.5f} pnl={num_fn(trade.get('pnl_usd')):+.2f}"
        )
    last_summary = status.get("last_summary") or {}
    expired = (last_summary.get("expired_labels") or {}).get("closed_count")
    lines = [
        "Paper AI dashboard",
        f"- Auto paper: {'ON' if status.get('enabled') else 'OFF'} | Shadow labels: {'ON' if status.get('shadow_labeling_enabled') else 'OFF'}",
        f"- Scan: every {status.get('scan_interval_seconds')}s | cooldown {status.get('cooldown_minutes')}m | max open {status.get('max_open_positions')}",
        f"- Label progress: {label_current}/{label_target} closed labels",
        f"- Remaining: {remaining} labels",
        f"- Open / Closed: {summary.get('open_count', 0)} / {summary.get('closed_count', 0)}",
        f"- Win rate: {((summary.get('win_rate') or 0) * 100):.1f}% ({summary.get('wins', 0)}W/{summary.get('losses', 0)}L)",
        f"- Profit factor: {profit_factor_text}",
        f"- Expectancy: {summary.get('expectancy_usd')}",
        f"- Closed PnL: {summary.get('closed_pnl_usd')} | Open PnL: {summary.get('open_unrealized_pnl_usd')}",
        f"- Live AI ready: {bool(gate.get('live_ready'))} | Mode: {gate.get('mode', 'unknown')}",
        f"- Blockers: {', '.join(gate.get('blockers', [])[:6]) or 'none'}",
    ]
    if expired is not None:
        lines.append(f"- Last expiry closed labels: {expired}")

    symbol_rows = [
        {"symbol": symbol, **stats}
        for symbol, stats in ((feedback or {}).get("symbol") or {}).items()
        if int(stats.get("trades", 0) or 0) >= 3
    ]
    symbol_rows.sort(key=lambda item: float(item.get("pnl", 0.0) or 0.0))
    if symbol_rows:
        weakest = symbol_rows[0]
        strongest = symbol_rows[-1]
        lines.append(
            f"- Weakest symbol: {weakest['symbol']} pnl={float(weakest.get('pnl', 0.0)):+.2f}, win={float(weakest.get('win_rate', 0.0)):.1f}%"
        )
        lines.append(
            f"- Strongest symbol: {strongest['symbol']} pnl={float(strongest.get('pnl', 0.0)):+.2f}, win={float(strongest.get('win_rate', 0.0)):.1f}%"
        )

    if quality:
        lines.append(f"- Trainable labels: {quality.get('included', 0)} included / {quality.get('excluded', 0)} pruned")
        reasons = quality.get("reasons") or {}
        if reasons:
            top_reason = sorted(reasons.items(), key=lambda item: int(item[1]), reverse=True)[0]
            lines.append(f"- Top pruning reason: {top_reason[0]} ({top_reason[1]})")

    if open_lines:
        lines.append("")
        lines.append("Open trades:")
        lines.extend(open_lines)
    lines.append("")
    lines.append("Next: keep collecting paper labels until quality gate passes.")
    return "\n".join(lines)


def _telegram_trade_keyboard(confirmation_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "Confirm Trade", "callback_data": f"tg:trade_confirm:{confirmation_id}"},
                {"text": "Cancel", "callback_data": f"tg:trade_cancel:{confirmation_id}"},
            ],
            [{"text": "Status", "callback_data": "tg:status"}],
        ]
    }


def _telegram_blocked_trade_keyboard(confirmation_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "Why blocked?", "callback_data": f"tg:why_blocked:{confirmation_id}"},
                {"text": "AI Progress", "callback_data": "tg:paper"},
            ],
            [{"text": "Open Paper Trade Instead", "callback_data": f"tg:paper_trade:{confirmation_id}"}],
            [{"text": "Status", "callback_data": "tg:status"}],
        ]
    }


def _telegram_extract_blockers(result: dict) -> list[dict]:
    readiness = result.get("readiness") or {}
    if isinstance(readiness, dict) and isinstance(readiness.get("blockers"), list):
        blockers = readiness.get("blockers") or []
        return [item if isinstance(item, dict) else {"name": str(item), "detail": ""} for item in blockers]
    preflight = result.get("preflight") or {}
    if isinstance(preflight, dict) and isinstance(preflight.get("issues"), list):
        return [{"name": "preflight", "detail": str(item)} for item in preflight.get("issues", [])]
    return []


def _telegram_format_blocked_trade(confirmation_id: str, result: dict, gate: dict[str, Any] | None = None) -> str:
    blockers = _telegram_extract_blockers(result)
    lines = [
        "Live order blocked safely.",
        f"ID: {confirmation_id}",
        f"Status: {result.get('status', 'BLOCKED')}",
        f"Message: {result.get('message', 'Live order blocked by safety gate.')}",
        "",
        "Reason:",
    ]
    if not blockers:
        lines.append("- Safety gate did not provide detailed blockers.")
    for blocker in blockers[:8]:
        name = str(blocker.get("name") or "blocker").replace("_", " ")
        detail = str(blocker.get("detail") or "").strip()
        lines.append(f"- {name}: {detail}" if detail else f"- {name}")

    progress = (gate or {}).get("paper_label_progress") or {}
    current = progress.get("current")
    target = progress.get("target")
    if current is not None and target:
        remaining = max(int(target) - int(current), 0)
        lines.extend(["", f"AI progress: {current}/{target} closed paper labels", f"Remaining: {remaining} labels"])

    lines.extend(
        [
            "",
            "Next:",
            "- Keep AI in paper/observe mode.",
            "- Use paper trade fallback to collect evidence without live risk.",
        ]
    )
    return "\n".join(lines)


def _telegram_format_blocked_detail(confirmation_id: str, request: dict, result: dict, gate: dict[str, Any] | None = None) -> str:
    return (
        f"Why blocked: {confirmation_id}\n"
        f"- Symbol: {request.get('symbol')}\n"
        f"- Side: {request.get('side')}\n"
        f"- Volume: {request.get('volume')}\n"
        f"- SL/TP: {request.get('sl')} / {request.get('tp')}\n\n"
        + _telegram_format_blocked_trade(confirmation_id, result, gate)
    )
