# -*- coding: utf-8 -*-
"""
Institutional-Grade Risk Manager

Implements five layers of risk control used by hedge funds and prop trading firms:
  1. Correlation filter      — no two highly-correlated positions open simultaneously
  2. Drawdown circuit breaker — pause trading after consecutive losses
  3. Kelly Criterion sizing  — size positions proportional to real edge (half-Kelly)
  4. Volatility-adjusted sizing — shrink size in high-ATR / high-VIX environments
  5. Funding rate gate       — avoid crowded long/short crypto positions
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

PAPER_DB = os.getenv("PAPER_TRADE_DB", "persistence.db")

# ─────────────────────────────────────────────────────────────────────────────
# 1. Correlation Groups
#    Assets in the same group are treated as highly correlated.
#    Only one signal per group is allowed at a time.
# ─────────────────────────────────────────────────────────────────────────────
CORRELATION_GROUPS: List[List[str]] = [
    ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD", "ADAUSD",
     "DOTUSD", "LINKUSD", "AVAXUSD", "LTCUSD", "ATOMUSD", "UNIUSD",
     "MATICUSD", "BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "AVAX",
     "LINK", "SOLUSDT", "XRPUSDT"],           # Crypto — high correlation
    ["EURUSD", "GBPUSD", "EURGBP", "AUDUSD", "NZDUSD"],   # Risk-on FX
    ["USDJPY", "USDCHF", "USDCAD"],                        # USD-strength FX
    ["GOLD", "SILVER", "XAUUSD"],                          # Precious metals
    ["NASDAQ", "SP500", "^DJI", "NVDA", "TSLA", "AAPL"],  # US equities
]


def get_correlation_group(symbol: str) -> Optional[List[str]]:
    sym = symbol.upper().strip()
    for group in CORRELATION_GROUPS:
        if sym in [s.upper() for s in group]:
            return group
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Drawdown Circuit Breaker
# ─────────────────────────────────────────────────────────────────────────────
CIRCUIT_BREAKER_CONSECUTIVE_LOSSES = int(os.getenv("CB_CONSECUTIVE_LOSSES", "5"))
CIRCUIT_BREAKER_COOLDOWN_MINUTES   = int(os.getenv("CB_COOLDOWN_MINUTES",   "120"))


def _get_recent_outcomes(symbol: Optional[str] = None, limit: int = 20) -> List[str]:
    """Return last N outcome strings ('WIN'/'LOSS') for symbol or all symbols."""
    try:
        with closing(sqlite3.connect(PAPER_DB)) as con:
            if symbol:
                rows = con.execute(
                    "SELECT outcome FROM paper_trades "
                    "WHERE status='CLOSED' AND outcome IS NOT NULL AND symbol=? "
                    "ORDER BY COALESCE(closed_at, opened_at) DESC LIMIT ?",
                    (symbol.upper(), limit),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT outcome FROM paper_trades "
                    "WHERE status='CLOSED' AND outcome IS NOT NULL "
                    "ORDER BY COALESCE(closed_at, opened_at) DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [str(r[0]).upper() for r in rows]
    except Exception:
        return []


def check_drawdown_circuit_breaker(symbol: Optional[str] = None) -> Dict[str, Any]:
    """
    Check for consecutive losses. Returns:
      {"ok": bool, "consecutive_losses": int, "blocked": bool, "reason": str}
    """
    outcomes = _get_recent_outcomes(symbol, limit=CIRCUIT_BREAKER_CONSECUTIVE_LOSSES + 5)
    consecutive = 0
    for o in outcomes:
        if o == "LOSS":
            consecutive += 1
        else:
            break

    blocked = consecutive >= CIRCUIT_BREAKER_CONSECUTIVE_LOSSES
    return {
        "ok":                not blocked,
        "consecutive_losses": consecutive,
        "blocked":            blocked,
        "threshold":          CIRCUIT_BREAKER_CONSECUTIVE_LOSSES,
        "reason":             f"{consecutive} consecutive losses — cooldown {CIRCUIT_BREAKER_COOLDOWN_MINUTES}m" if blocked else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Kelly Criterion Position Sizing (Half-Kelly for safety)
# ─────────────────────────────────────────────────────────────────────────────
KELLY_FRACTION  = float(os.getenv("KELLY_FRACTION",  "0.5"))   # half-Kelly
KELLY_MAX_RISK  = float(os.getenv("KELLY_MAX_RISK",  "3.0"))   # cap at 3% per trade
KELLY_MIN_RISK  = float(os.getenv("KELLY_MIN_RISK",  "0.25"))  # floor at 0.25%


def kelly_position_size(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    balance: float = 1000.0,
    base_risk_pct: float = 1.0,
) -> Dict[str, float]:
    """
    Compute Kelly-optimal position size.

    Kelly fraction = (W * b - L) / b
      where b = avg_win / avg_loss (payoff ratio)
            W = win rate, L = loss rate

    Returns half-Kelly capped between KELLY_MIN_RISK and KELLY_MAX_RISK.
    """
    win_rate   = max(0.01, min(0.99, float(win_rate)))
    loss_rate  = 1.0 - win_rate
    avg_win    = max(0.001, float(avg_win_pct))
    avg_loss   = max(0.001, float(avg_loss_pct))
    payoff     = avg_win / avg_loss

    kelly_full = (win_rate * payoff - loss_rate) / payoff
    kelly_half = kelly_full * KELLY_FRACTION

    risk_pct   = max(KELLY_MIN_RISK, min(KELLY_MAX_RISK, kelly_half * 100))
    risk_usd   = balance * risk_pct / 100.0

    return {
        "kelly_full_pct":  round(kelly_full * 100, 3),
        "kelly_half_pct":  round(kelly_half * 100, 3),
        "recommended_risk_pct": round(risk_pct, 3),
        "recommended_risk_usd": round(risk_usd, 4),
        "payoff_ratio":    round(payoff, 3),
        "win_rate":        round(win_rate, 4),
        "positive_edge":   kelly_full > 0,
    }


def kelly_from_paper_trades(symbol: Optional[str] = None, limit: int = 100) -> Dict[str, float]:
    """Compute Kelly sizing from actual paper trade history."""
    try:
        query = """
            SELECT outcome, pnl_usd, entry_price
            FROM paper_trades
            WHERE status='CLOSED' AND outcome IS NOT NULL AND entry_price > 0
        """
        params: tuple = ()
        if symbol:
            query += " AND symbol=?"
            params = (symbol.upper(),)
        query += " ORDER BY COALESCE(closed_at, opened_at) DESC LIMIT ?"
        params = params + (limit,)
        with closing(sqlite3.connect(PAPER_DB)) as con:
            rows = con.execute(query, params).fetchall()
    except Exception:
        return {"available": False}

    if len(rows) < 10:
        return {"available": False, "reason": f"insufficient trades ({len(rows)})"}

    wins   = [abs(float(r[1])) for r in rows if str(r[0]).upper() == "WIN"  and r[1] is not None]
    losses = [abs(float(r[1])) for r in rows if str(r[0]).upper() == "LOSS" and r[1] is not None]

    if not wins or not losses:
        return {"available": False, "reason": "no wins or losses to compute edge"}

    win_rate   = len(wins) / len(rows)
    avg_win    = float(np.mean(wins))
    avg_loss   = float(np.mean(losses))

    result = kelly_position_size(win_rate, avg_win, avg_loss)
    result["available"] = True
    result["n_trades"]  = len(rows)
    result["symbol"]    = symbol or "ALL"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 4. Volatility-Adjusted Position Sizing
# ─────────────────────────────────────────────────────────────────────────────
VOL_TARGET_ATR_PCT = float(os.getenv("VOL_TARGET_ATR_PCT", "1.5"))  # target 1.5% ATR


def volatility_adjusted_size(
    base_risk_pct: float,
    atr_pct: float,
    vix: float = 0.0,
) -> Dict[str, float]:
    """
    Scale position size down when market is more volatile than target.

    vol_scalar = target_atr / current_atr  (capped 0.25–1.5)
    vix_scalar = 1.0 if VIX < 20, scales down to 0.5 at VIX=40
    """
    atr_pct = max(0.01, float(atr_pct))
    vol_scalar = min(1.5, max(0.25, VOL_TARGET_ATR_PCT / atr_pct))

    vix_scalar = 1.0
    if vix > 0:
        # Linear scale: VIX 20 → 1.0, VIX 40 → 0.5
        vix_scalar = max(0.3, min(1.0, 1.0 - (max(0.0, vix - 20.0) / 40.0)))

    adjusted_risk = base_risk_pct * vol_scalar * vix_scalar

    return {
        "base_risk_pct":     round(base_risk_pct, 3),
        "adjusted_risk_pct": round(adjusted_risk, 3),
        "vol_scalar":        round(vol_scalar, 3),
        "vix_scalar":        round(vix_scalar, 3),
        "atr_pct":           round(atr_pct, 3),
        "vix":               round(vix, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Funding Rate Gate (Binance Perpetuals)
# ─────────────────────────────────────────────────────────────────────────────
FUNDING_HIGH_LONG_BLOCK  = float(os.getenv("FUNDING_HIGH_LONG_BLOCK",  "0.001"))   # +0.1%
FUNDING_HIGH_SHORT_BLOCK = float(os.getenv("FUNDING_HIGH_SHORT_BLOCK", "-0.001"))  # -0.1%

_FUNDING_CACHE: Dict[str, Dict] = {}
_FUNDING_CACHE_TTL = 600  # 10 minutes


def _binance_symbol(symbol: str) -> str:
    sym = symbol.upper().replace("USD", "USDT").replace("USDT", "")
    return sym + "USDT"


def get_funding_rate(symbol: str) -> Optional[float]:
    """Fetch current funding rate from Binance. Returns None if unavailable."""
    import time
    cache_key = _binance_symbol(symbol)
    cached = _FUNDING_CACHE.get(cache_key, {})
    if cached and time.time() - cached.get("ts", 0) < _FUNDING_CACHE_TTL:
        return cached.get("rate")

    try:
        import urllib.request
        import json
        url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={cache_key}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        rate = float(data.get("lastFundingRate", 0))
        _FUNDING_CACHE[cache_key] = {"rate": rate, "ts": time.time()}
        return rate
    except Exception:
        return None


def check_funding_rate_gate(symbol: str, side: str) -> Dict[str, Any]:
    """
    Block entries when funding rate indicates an extremely crowded position.
    High positive funding → too many longs → fade / don't buy
    High negative funding → too many shorts → fade / don't sell
    """
    rate = get_funding_rate(symbol)
    if rate is None:
        return {"ok": True, "rate": None, "checked": False}

    side = side.upper()
    blocked = False
    reason  = ""

    if side == "BUY" and rate >= FUNDING_HIGH_LONG_BLOCK:
        blocked = True
        reason  = f"Funding {rate*100:+.3f}% — longs too crowded, avoid BUY"
    elif side == "SELL" and rate <= FUNDING_HIGH_SHORT_BLOCK:
        blocked = True
        reason  = f"Funding {rate*100:+.3f}% — shorts too crowded, avoid SELL"

    return {
        "ok":      not blocked,
        "blocked": blocked,
        "rate":    round(rate, 6),
        "rate_pct": round(rate * 100, 4),
        "side":    side,
        "reason":  reason,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Combined Risk Check
# ─────────────────────────────────────────────────────────────────────────────

def full_risk_check(
    symbol: str,
    side: str,
    win_probability: float = 0.5,
    atr_pct: float = 1.0,
    vix: float = 0.0,
    open_symbols: Optional[List[str]] = None,
    balance: float = 1000.0,
    asset_class: str = "CRYPTO",
) -> Dict[str, Any]:
    """
    Run all five risk checks. Returns a unified result dict.

    ok=True  → trade is allowed, includes recommended sizing
    ok=False → trade is blocked, includes reason
    """
    result: Dict[str, Any] = {
        "symbol":  symbol.upper(),
        "side":    side.upper(),
        "ok":      True,
        "blocked_by": [],
        "warnings": [],
    }

    # 1. Correlation filter
    if open_symbols:
        group = get_correlation_group(symbol)
        if group:
            group_upper = [s.upper() for s in group]
            conflicts = [s for s in open_symbols if s.upper() in group_upper and s.upper() != symbol.upper()]
            if conflicts:
                result["ok"] = False
                result["blocked_by"].append("correlation")
                result["correlation_conflict"] = conflicts
                result["warnings"].append(f"Already have position in correlated asset: {conflicts[0]}")

    # 2. Drawdown circuit breaker
    cb = check_drawdown_circuit_breaker(symbol)
    result["circuit_breaker"] = cb
    if cb["blocked"]:
        result["ok"] = False
        result["blocked_by"].append("drawdown_circuit_breaker")
        result["warnings"].append(cb["reason"])

    # 3. Funding rate (Crypto only)
    funding = {"ok": True, "checked": False}
    if asset_class.upper() == "CRYPTO":
        funding = check_funding_rate_gate(symbol, side)
        if funding["blocked"]:
            result["ok"] = False
            result["blocked_by"].append("funding_rate")
            result["warnings"].append(funding.get("reason", ""))
    result["funding"] = funding

    # 4 & 5. Kelly + volatility sizing
    kelly = kelly_from_paper_trades(symbol)
    if not kelly.get("available") or not kelly.get("positive_edge"):
        base_risk = 1.0
    else:
        base_risk = kelly["recommended_risk_pct"]

    vol_size = volatility_adjusted_size(base_risk, atr_pct, vix)
    result["sizing"] = {
        "kelly":         kelly,
        "vol_adjusted":  vol_size,
        "final_risk_pct": vol_size["adjusted_risk_pct"],
    }

    if vol_size["adjusted_risk_pct"] < 0.1:
        result["warnings"].append(f"Position too small ({vol_size['adjusted_risk_pct']:.2f}%) — skip")

    return result
