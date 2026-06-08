from __future__ import annotations

import re
from typing import Any, Callable


def _telegram_parse_alert_request(
    text: str,
    *,
    symbol_extractor: Callable[[str, str], str],
    live_price_fn: Callable[[str], float],
    trigger_terms: tuple[str, ...] = ("/alert", "alert"),
    above_terms: tuple[str, ...] = ("above", "over", ">"),
    below_terms: tuple[str, ...] = ("below", "under", "<"),
) -> dict | None:
    raw = str(text or "").strip()
    lower = raw.lower()
    if not any(term in lower for term in trigger_terms):
        return None

    parts = raw.split()
    symbol = (
        parts[1].upper().strip()
        if parts and parts[0].lower() == "/alert" and len(parts) > 1
        else symbol_extractor(raw, "")
    )
    if not symbol:
        return None

    price_matches = re.findall(r"(?<![A-Za-z])(\d+(?:,\d{3})*(?:\.\d+)?)", raw)
    if not price_matches:
        return None
    price = float(price_matches[-1].replace(",", ""))
    if price <= 0:
        return None

    if any(word in lower for word in above_terms):
        condition = "above"
    elif any(word in lower for word in below_terms):
        condition = "below"
    else:
        live_price = live_price_fn(symbol)
        condition = "above" if live_price <= 0 or price >= live_price else "below"

    symbol = symbol.upper().strip()
    return {
        "symbol": symbol,
        "condition": condition,
        "price": price,
        "timeframe": "15m",
        "message": f"Telegram alert: {symbol} {condition} {price}",
    }


def _build_best_entry_alert_request(top: dict[str, Any], payload: dict[str, Any], *, num_fn) -> dict[str, Any]:
    entry = top.get("entry_zone") or {}
    entry_low = num_fn(entry.get("low"))
    entry_high = num_fn(entry.get("high"))
    price = num_fn(top.get("price"))
    side = str(top.get("side") or "").upper()
    decision = top.get("entry_decision") or {}
    if not entry_low or not entry_high:
        raise ValueError("Best setup has no complete entry zone")

    if side == "BUY":
        alert_price = entry_high if price and price > entry_high else entry_low
        condition = "below" if price and price > entry_high else "above"
    elif side == "SELL":
        alert_price = entry_low if price and price < entry_low else entry_high
        condition = "above" if price and price < entry_low else "below"
    else:
        alert_price = (entry_low + entry_high) / 2.0
        condition = "above"

    return {
        "symbol": top.get("symbol"),
        "condition": condition,
        "price": float(alert_price),
        "timeframe": "15m",
        "message": (
            f"Best setup entry alert: {top.get('symbol')} {side} "
            f"{condition} {float(alert_price):.5f} | decision={decision.get('action', 'WAIT')}"
        ),
        "metadata": {
            "side": side,
            "decision": decision.get("action"),
            "no_trade": bool(payload.get("no_trade")),
            "no_trade_reason": payload.get("no_trade_reason"),
        },
    }


def _build_best_confirmation_alert_request(top: dict[str, Any], payload: dict[str, Any], *, num_fn) -> dict[str, Any]:
    entry = top.get("entry_zone") or {}
    entry_low = num_fn(entry.get("low"))
    entry_high = num_fn(entry.get("high"))
    price = num_fn(top.get("price"))
    side = str(top.get("side") or "").upper()
    if not entry_low or not entry_high:
        raise ValueError("Best setup has no complete entry zone")

    if side == "BUY":
        alert_price = entry_low if price and price < entry_low else entry_high
        condition = "above"
    elif side == "SELL":
        alert_price = entry_high if price and price > entry_high else entry_low
        condition = "below"
    else:
        alert_price = (entry_low + entry_high) / 2.0
        condition = "above"

    return {
        "symbol": top.get("symbol"),
        "condition": condition,
        "price": float(alert_price),
        "timeframe": "15m",
        "message": (
            f"Best setup confirmation alert: {top.get('symbol')} {side} "
            f"{condition} {float(alert_price):.5f}. Re-check momentum, spread, RR, and risk guard before entry."
        ),
        "metadata": {
            "side": side,
            "decision": (top.get("entry_decision") or {}).get("action"),
            "no_trade": bool(payload.get("no_trade")),
            "no_trade_reason": payload.get("no_trade_reason"),
            "confirmation_required": True,
        },
    }
