from __future__ import annotations

import re
from typing import Any


TRADE_SYMBOL_ALIASES: dict[str, list[str]] = {
    "BTC": ["BTC", "BTCUSD", "BTCUSDT", "XBTUSD"],
    "BTCUSD": ["BTCUSD", "BTC", "BTCUSDT", "XBTUSD"],
    "BTCUSDT": ["BTCUSDT", "BTCUSD", "BTC", "XBTUSD"],
    "ETH": ["ETH", "ETHUSD", "ETHUSDT"],
    "ETHUSD": ["ETHUSD", "ETH", "ETHUSDT"],
    "ETHUSDT": ["ETHUSDT", "ETHUSD", "ETH"],
    "GOLD": ["GOLD", "XAUUSD", "XAU", "XAUUSD.M", "XAUUSDm"],
    "XAU": ["XAU", "XAUUSD", "GOLD", "XAUUSD.M", "XAUUSDm"],
    "XAUUSD": ["XAUUSD", "GOLD", "XAU", "XAUUSD.M", "XAUUSDm"],
    "NAS100": ["NAS100", "NASDAQ", "USTEC", "US100"],
    "NASDAQ": ["NASDAQ", "NAS100", "USTEC", "US100"],
    "SP500": ["SP500", "US500", "SPX500", "S&P500"],
    "EURUSD": ["EURUSD", "EUR/USD"],
}


def _telegram_extract_symbol(text: str, default: str = "BTC") -> str:
    cleaned = str(text or "").upper()
    ignored = {"WATCH", "LOOK", "TRADE", "ALERT", "PRICE", "RISK", "ENTRY", "WITH", "AND", "NOW", "AT"}
    aliases = {
        "GOLD": "GOLD",
        "เธ—เธญเธ": "GOLD",
        "XAU": "GOLD",
        "XAUUSD": "GOLD",
        "เธเนเธณเธกเธฑเธ": "OIL",
        "WTI": "OIL",
        "NASDAQ": "NASDAQ",
        "NAS100": "NASDAQ",
        "SP500": "SP500",
        "S&P": "SP500",
        "EURO": "EURUSD",
        "EUR/USD": "EURUSD",
        "EURUSD": "EURUSD",
    }
    for key, value in aliases.items():
        if key.upper() in cleaned:
            return value
    for match in re.findall(r"\b([A-Z]{2,8}(?:USD|USDT)?|[A-Z]{3,6}/[A-Z]{3})\b", cleaned):
        if match not in ignored and ("/" in match or match.endswith(("USD", "USDT"))):
            return match.replace("/", "")
    return default


def _trade_symbol_aliases(symbol: str | None) -> list[str]:
    raw = str(symbol or "").upper().strip().replace("/", "")
    if not raw:
        return []
    aliases = TRADE_SYMBOL_ALIASES.get(raw, [raw])
    seen: set[str] = set()
    result: list[str] = []
    for item in [raw, *aliases]:
        clean = str(item or "").upper().strip().replace("/", "")
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _canonical_trade_symbol(symbol: str | None) -> str:
    aliases = _trade_symbol_aliases(symbol)
    if not aliases:
        return ""
    if "XAUUSD" in aliases:
        return "GOLD"
    if "BTCUSD" in aliases:
        return "BTCUSD"
    if "ETHUSD" in aliases:
        return "ETHUSD"
    return aliases[0]


def resolve_trade_symbol(symbol: str | None) -> dict[str, Any]:
    raw = str(symbol or "").upper().strip().replace("/", "")
    canonical = _canonical_trade_symbol(raw)
    aliases = _trade_symbol_aliases(canonical or raw)
    tactics_symbol = canonical
    if canonical in {"BTCUSD", "ETHUSD"}:
        tactics_symbol = canonical[:-3]
    elif canonical == "GOLD":
        tactics_symbol = "GOLD"
    elif canonical.endswith("USDT"):
        tactics_symbol = canonical[:-4]
    paper_symbol = canonical
    if canonical == "BTC":
        paper_symbol = "BTCUSD"
    elif canonical == "ETH":
        paper_symbol = "ETHUSD"
    elif canonical == "SOL":
        paper_symbol = "SOLUSDT"
    elif canonical == "XRP":
        paper_symbol = "XRPUSDT"
    quick_symbol = tactics_symbol
    broker_candidates = aliases or [canonical or raw]
    return {
        "raw": raw,
        "canonical": canonical or raw,
        "aliases": aliases,
        "tactics_symbol": tactics_symbol,
        "paper_symbol": paper_symbol,
        "quick_symbol": quick_symbol,
        "broker_candidates": broker_candidates,
    }


def _telegram_symbols_from_text(text: str) -> list[str]:
    cleaned = str(text or "").upper()
    symbols: set[str] = set()
    alias_map = {
        "เธ—เธญเธ": "GOLD",
        "XAU": "GOLD",
        "XAUUSD": "GOLD",
        "BTC": "BTC",
        "ETH": "ETH",
        "SOL": "SOL",
        "XRP": "XRP",
        "EURUSD": "EURUSD",
        "NASDAQ": "NASDAQ",
        "NAS100": "NASDAQ",
        "SP500": "SP500",
        "S&P": "SP500",
        "OIL": "OIL",
        "WTI": "OIL",
        "เธเนเธณเธกเธฑเธ": "OIL",
    }
    for key, value in alias_map.items():
        if key.upper() in cleaned:
            symbols.add(value)
    ignored = {"LOT", "BUY", "SELL", "HOLD", "STOP", "RISK", "ENTRY", "PRICE", "ALERT", "WATCH", "AND", "WITH", "TRADE"}
    for match in re.findall(r"\b[A-Z]{2,8}(?:USD|USDT)?\b", cleaned):
        if match not in ignored:
            symbols.add(match.replace("USDT", "USD"))
    return sorted(symbols)
