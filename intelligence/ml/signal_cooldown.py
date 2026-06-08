"""
Signal Zone Cooldown

Prevents the system from re-entering the same OB/FVG zone on the same symbol
before price has meaningfully moved away.  Tracks the last fired signal per
(symbol, timeframe, direction) and blocks new signals whose entry midpoint is
within ZONE_PROXIMITY_PCT of the last one before the cooldown expires.
"""
import time

_REGISTRY: dict = {}   # (symbol, tf, direction) → (timestamp, zone_mid)

ZONE_PROXIMITY_PCT = 0.005   # 0.5% — same zone if entry mids within 0.5%

# Cooldown by timeframe (seconds)
_TF_COOLDOWN = {
    "15m": 4  * 3600,
    "1h":  8  * 3600,
    "4h":  24 * 3600,
    "1d":  72 * 3600,
}
_DEFAULT_COOLDOWN = 6 * 3600


def check(symbol: str, timeframe: str, direction: str, zone_mid: float) -> dict:
    """
    Returns {"cooling_down": bool, "reason": str, "remaining_minutes": int}
    """
    key   = (symbol.upper(), timeframe, direction.upper())
    entry = _REGISTRY.get(key)
    if not entry:
        return {"cooling_down": False, "reason": ""}

    last_time, last_zone = entry
    cooldown_secs = _TF_COOLDOWN.get(timeframe, _DEFAULT_COOLDOWN)
    elapsed       = time.time() - last_time

    if elapsed >= cooldown_secs:
        return {"cooling_down": False, "reason": ""}

    if zone_mid > 0 and last_zone > 0:
        zone_diff_pct = abs(zone_mid - last_zone) / max(last_zone, 1e-9)
        if zone_diff_pct > ZONE_PROXIMITY_PCT:
            return {"cooling_down": False, "reason": ""}

    remaining = max(0, int(cooldown_secs - elapsed) // 60)
    return {
        "cooling_down":     True,
        "reason":           f"same zone ({last_zone:.2f}) already traded {int(elapsed//60)}m ago — {remaining}m cooldown left",
        "remaining_minutes": remaining,
    }


def register(symbol: str, timeframe: str, direction: str, zone_mid: float) -> None:
    """Record a confirmed signal so future calls to check() can detect duplicates."""
    key = (symbol.upper(), timeframe, direction.upper())
    _REGISTRY[key] = (time.time(), zone_mid)


def clear(symbol: str = None) -> None:
    """Clear registry (all symbols, or just one)."""
    if symbol is None:
        _REGISTRY.clear()
    else:
        keys = [k for k in _REGISTRY if k[0] == symbol.upper()]
        for k in keys:
            del _REGISTRY[k]
