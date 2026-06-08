"""
Adaptive per-symbol and per-side confidence thresholds from paper outcomes.

The project already records realized paper-trade performance. This module
turns that evidence into symbol-aware confidence floors so weak slices need
higher conviction before they can surface as actionable signals.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Dict

logger = logging.getLogger(__name__)

THRESHOLD_FILE = "data/symbol_thresholds.json"
DEFAULT_THRESHOLD = 0.50
MIN_TRADES = 10
SIDE_MIN_TRADES = 3
STOCK_SYMBOLS = {
    "AAPL", "AMD", "AMZN", "BAC", "GOOG", "GOOGL", "JPM", "META", "MSFT",
    "NFLX", "NVDA", "QQQ", "SPY", "TSLA", "UBER",
}


def _is_stock_like(symbol: str) -> bool:
    normalized = str(symbol or "").upper().replace("#", "")
    return normalized in STOCK_SYMBOLS


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").upper().strip()
    if normalized.endswith("USDT"):
        normalized = normalized[:-4]
    return normalized


def _normalize_side(side: str | None) -> str:
    return str(side or "").upper().strip()


def _win_rate_to_floor(win_rate: float, n_trades: int) -> float:
    if n_trades < MIN_TRADES:
        if n_trades >= 3 and win_rate < 0.35:
            return 0.62
        return DEFAULT_THRESHOLD
    if win_rate >= 0.52:
        return 0.50
    if win_rate >= 0.45:
        return 0.55
    if win_rate >= 0.38:
        return 0.62
    return 0.70


def _side_floor(win_rate: float, n_trades: int, pnl: float) -> float:
    if n_trades < SIDE_MIN_TRADES:
        return DEFAULT_THRESHOLD
    floor = _win_rate_to_floor(win_rate, max(n_trades, MIN_TRADES))
    if pnl < 0:
        floor = max(floor, 0.62)
    if n_trades >= 5 and (win_rate < 0.40 or pnl < -1.0):
        floor = max(floor, 0.68)
    return floor


def update_thresholds() -> Dict[str, float]:
    db_path = os.environ.get("PAPER_TRADE_DB", "persistence.db")
    if not os.path.exists(db_path):
        return {}

    thresholds: Dict[str, float] = {}
    con: sqlite3.Connection | None = None
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()

        cur.execute(
            """
            SELECT symbol,
                   COUNT(*) AS n,
                   SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins
            FROM paper_trades
            WHERE status='CLOSED' AND outcome IS NOT NULL
            GROUP BY symbol
            """
        )
        for symbol, n, wins in cur.fetchall():
            normalized_symbol = _normalize_symbol(symbol)
            if _is_stock_like(normalized_symbol):
                continue
            win_rate = (wins or 0) / n if n else 0.5
            floor = _win_rate_to_floor(win_rate, int(n or 0))
            thresholds[normalized_symbol] = floor
            logger.info(
                "SymbolThreshold [%s]: win_rate=%.1f%% n=%s -> floor=%.2f",
                normalized_symbol,
                win_rate * 100.0,
                n,
                floor,
            )

        cur.execute(
            """
            SELECT symbol,
                   UPPER(COALESCE(side, '')) AS side,
                   COUNT(*) AS n,
                   SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                   SUM(COALESCE(pnl_usd, 0.0)) AS pnl
            FROM paper_trades
            WHERE status='CLOSED' AND outcome IS NOT NULL
            GROUP BY symbol, UPPER(COALESCE(side, ''))
            """
        )
        for symbol, side, n, wins, pnl in cur.fetchall():
            normalized_symbol = _normalize_symbol(symbol)
            normalized_side = _normalize_side(side)
            if _is_stock_like(normalized_symbol) or not normalized_side:
                continue
            win_rate = (wins or 0) / n if n else 0.5
            floor = _side_floor(win_rate, int(n or 0), float(pnl or 0.0))
            thresholds[f"{normalized_symbol}:{normalized_side}"] = floor
            logger.info(
                "SymbolThreshold [%s %s]: win_rate=%.1f%% n=%s pnl=%+.2f -> floor=%.2f",
                normalized_symbol,
                normalized_side,
                win_rate * 100.0,
                n,
                float(pnl or 0.0),
                floor,
            )
        os.makedirs("data", exist_ok=True)
        with open(THRESHOLD_FILE, "w", encoding="utf-8") as handle:
            json.dump(thresholds, handle, indent=2, sort_keys=True)
    except Exception as exc:
        logger.warning("SymbolThreshold: update failed: %s", exc)
    finally:
        if con is not None:
            con.close()

    return thresholds


def load_thresholds() -> Dict[str, float]:
    try:
        if os.path.exists(THRESHOLD_FILE):
            with open(THRESHOLD_FILE, encoding="utf-8") as handle:
                return json.load(handle)
    except Exception:
        pass
    return {}


_CACHE: Dict[str, float] = load_thresholds()


def refresh_threshold_cache() -> Dict[str, float]:
    global _CACHE
    _CACHE = update_thresholds()
    return _CACHE


def get_threshold(symbol: str) -> float:
    normalized_symbol = _normalize_symbol(symbol)
    base_symbol = normalized_symbol.replace("USD", "")
    for key in [normalized_symbol, base_symbol, f"{base_symbol}USD"]:
        if key in _CACHE:
            return _CACHE[key]
    return DEFAULT_THRESHOLD


def get_threshold_for_side(symbol: str, side: str | None = None) -> float:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_side = _normalize_side(side)
    base_symbol = normalized_symbol.replace("USD", "")
    lookup = []
    if normalized_side:
        lookup.extend(
            [
                f"{normalized_symbol}:{normalized_side}",
                f"{base_symbol}:{normalized_side}",
                f"{base_symbol}USD:{normalized_side}",
            ]
        )
    lookup.extend([normalized_symbol, base_symbol, f"{base_symbol}USD"])
    for key in lookup:
        if key in _CACHE:
            return _CACHE[key]
    return DEFAULT_THRESHOLD
