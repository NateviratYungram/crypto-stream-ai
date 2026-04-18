"""
CryptoStream AI — Hyperliquid Price Fetcher
Real-time and historical crypto prices from Hyperliquid public API (no API key required).

Ported from AI-Trader price_fetcher.py — adapted for CryptoStream:
  - Extracted only the Hyperliquid functions (dropped Alpha Vantage / Polymarket)
  - Added exponential backoff retry (2 attempts, 0.35s base delay)
  - Symbol normalization: "BTCUSDT" → "BTC", "BTC-USD" → "BTC"
  - Used by TradeLogger.update_trade_close() to fill actual entry/exit prices

Endpoints used (all public, no auth):
  POST https://api.hyperliquid.xyz/info  { type: "l2Book",       coin: "BTC" }
  POST https://api.hyperliquid.xyz/info  { type: "candleSnapshot", req: {...} }

Usage:
    from intelligence.hyperliquid_price import get_hl_mid_price, get_hl_price_at

    price = get_hl_mid_price("BTC")           # current mid price
    price = get_hl_price_at("ETH", "2025-01-01T10:00:00Z")  # historical
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_HL_URL = "https://api.hyperliquid.xyz/info"
_TIMEOUT = 10
_MAX_RETRIES = 2
_BACKOFF_BASE = 0.35   # seconds


# ── Symbol normalisation ───────────────────────────────────────────────────────

def _normalise(symbol: str) -> str:
    """
    Convert any crypto symbol format to a Hyperliquid coin identifier.
    Examples:
      "BTCUSDT"  → "BTC"
      "BTC-USD"  → "BTC"
      "BTC/USD"  → "BTC"
      "BTC-PERP" → "BTC"
      "eth"      → "ETH"
    """
    raw = (symbol or "").strip()
    if ":" in raw:
        return raw   # dex-prefixed identifiers are passed through as-is

    s = raw.upper()
    for suffix in ("-PERP", "PERP", "USDT", "-USD", "/USD", "-USDT", "/USDT"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s.strip()


# ── HTTP helper ────────────────────────────────────────────────────────────────

def _post(payload: dict) -> object:
    """POST to Hyperliquid info endpoint with retry + backoff."""
    import requests
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = requests.post(_HL_URL, json=payload, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                delay = _BACKOFF_BASE * (2 ** attempt)
                time.sleep(delay)
    raise last_exc or RuntimeError("Hyperliquid request failed")


# ── Mid price (real-time) ──────────────────────────────────────────────────────

def get_hl_mid_price(symbol: str) -> Optional[float]:
    """
    Fetch real-time mid price from Hyperliquid L2 orderbook.

    Args:
        symbol : any format, e.g. "BTC", "ETHUSDT", "SOL-PERP"

    Returns:
        float mid price, or None on failure
    """
    coin = _normalise(symbol)
    try:
        data = _post({"type": "l2Book", "coin": coin})
        if not isinstance(data, dict) or "levels" not in data:
            return None
        levels = data["levels"]
        if not isinstance(levels, list) or len(levels) < 2:
            return None

        bids = levels[0] if isinstance(levels[0], list) else []
        asks = levels[1] if isinstance(levels[1], list) else []

        best_bid = float(bids[0]["px"]) if bids and isinstance(bids[0], dict) and "px" in bids[0] else None
        best_ask = float(asks[0]["px"]) if asks and isinstance(asks[0], dict) and "px" in asks[0] else None

        if best_bid is None and best_ask is None:
            return None
        if best_bid is not None and best_ask is not None:
            return round((best_bid + best_ask) / 2, 6)
        return round(best_bid if best_bid is not None else best_ask, 6)  # type: ignore[arg-type]
    except Exception as e:
        logger.warning(f"hyperliquid_price.get_hl_mid_price({symbol}): {e}")
        return None


# ── Historical candle close ────────────────────────────────────────────────────

def _parse_utc(ts: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp to UTC datetime."""
    try:
        cleaned = ts.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def get_hl_price_at(symbol: str, executed_at: str) -> Optional[float]:
    """
    Fetch the closest 1-minute candle close price at or before `executed_at`.
    Queries a ±10-minute window around the target time.

    Args:
        symbol      : crypto symbol, e.g. "BTC"
        executed_at : ISO 8601 timestamp, e.g. "2025-01-01T10:30:00Z"

    Returns:
        float close price, or None on failure
    """
    dt = _parse_utc(executed_at)
    if not dt:
        logger.warning(f"hyperliquid_price: could not parse timestamp '{executed_at}'")
        return None

    coin       = _normalise(symbol)
    target_ms  = int(dt.timestamp() * 1000)
    start_ms   = target_ms - 10 * 60 * 1000   # −10 min
    end_ms     = target_ms + 10 * 60 * 1000   # +10 min

    try:
        data = _post({
            "type": "candleSnapshot",
            "req": {
                "coin":      coin,
                "interval":  "1m",
                "startTime": start_ms,
                "endTime":   end_ms,
            },
        })
        if not isinstance(data, list) or len(data) == 0:
            return None

        # Pick the candle with the largest timestamp ≤ target
        best_ts: Optional[int]   = None
        best_close: Optional[float] = None

        for candle in data:
            if not isinstance(candle, dict):
                continue
            t = candle.get("t")
            c = candle.get("c")
            if t is None or c is None:
                continue
            try:
                t_ms   = int(float(t))
                close  = float(c)
            except Exception:
                continue
            if t_ms > target_ms:
                continue
            if best_ts is None or t_ms > best_ts:
                best_ts    = t_ms
                best_close = close

        return round(best_close, 6) if best_close is not None else None

    except Exception as e:
        logger.warning(f"hyperliquid_price.get_hl_price_at({symbol}, {executed_at}): {e}")
        return None


# ── Convenience: fill trade price ─────────────────────────────────────────────

def fill_trade_price(symbol: str, executed_at: Optional[str] = None) -> Optional[float]:
    """
    Get the best available price for a trade:
      1. Historical candle close if executed_at is provided
      2. Current mid price as fallback

    Intended for use with TradeLogger.update_trade_close().
    """
    if executed_at:
        price = get_hl_price_at(symbol, executed_at)
        if price:
            return price
    return get_hl_mid_price(symbol)
