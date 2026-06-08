from __future__ import annotations

import hashlib
import re
from typing import Any, Callable


def _news_watch_aliases(symbol: str) -> list[str]:
    normalized = str(symbol or "").upper().replace("/", "").replace("-", "")
    aliases = {normalized}
    if normalized in {"BTC", "BTCUSD", "BTCUSDT"}:
        aliases.update({"BTC", "BITCOIN", "BTCUSD", "BTCUSDT"})
    elif normalized in {"ETH", "ETHUSD", "ETHUSDT"}:
        aliases.update({"ETH", "ETHEREUM", "ETHUSD", "ETHUSDT"})
    elif normalized in {"SOL", "SOLUSD", "SOLUSDT"}:
        aliases.update({"SOL", "SOLANA", "SOLUSD", "SOLUSDT"})
    elif normalized in {"XAUUSD", "GOLD", "XAU"}:
        aliases.update({"GOLD", "XAU", "XAUUSD"})
    elif normalized in {"SP500", "SPX", "GSPC"}:
        aliases.update({"SP500", "S&P 500", "SPX", "GSPC"})
    elif normalized in {"NASDAQ", "NASDAQ100", "NDX"}:
        aliases.update({"NASDAQ", "NASDAQ 100", "NASDAQ100", "NDX"})
    return sorted(alias for alias in aliases if alias)


def _extract_news_watch_symbol(
    text: str,
    default: str = "BTC",
    *,
    trade_symbol_aliases: dict[str, Any] | None = None,
    fallback_extractor: Callable[[str, str], str] | None = None,
) -> str:
    raw = str(text or "").strip()
    upper = raw.upper()
    if any(term in upper for term in {"CRYPTO", "BITCOIN MARKET"}):
        return "BTC"
    if any(term in upper for term in {"STOCK", "EQUITY"}):
        return "SP500"
    if any(term in upper for term in {"FOREX", "FX"}):
        return "EURUSD"

    alias_map = {
        "BITCOIN": "BTC",
        "BTC": "BTC",
        "ETHEREUM": "ETH",
        "ETH": "ETH",
        "SOLANA": "SOL",
        "SOL": "SOL",
        "GOLD": "GOLD",
        "XAU": "GOLD",
        "XAUUSD": "GOLD",
        "NASDAQ": "NASDAQ",
        "NAS100": "NASDAQ",
        "SP500": "SP500",
        "S&P500": "SP500",
        "OIL": "OIL",
        "WTI": "OIL",
    }
    for needle, symbol in alias_map.items():
        if needle in upper:
            return symbol

    stopwords = {
        "IF", "THERE", "IS", "BIG", "NOTIFY", "ME", "PLEASE",
        "NEWS", "ALERT", "HEADLINE", "HEADLINES", "WHEN", "ABOUT", "FOR",
        "WHAT", "LATEST", "TONE", "BULLISH", "BEARISH", "AND", "THE", "OF",
        "BREAKING", "HEADLINE", "SEND", "TELEGRAM", "WATCH", "THIS", "THAT", "WHEN",
    }
    known = set(trade_symbol_aliases or {})
    known.update({"BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "GOLD", "NASDAQ", "SP500", "OIL", "EURUSD"})
    tokens = re.findall(r"\b[A-Z]{2,10}\b", upper)
    for token in tokens:
        if token in stopwords:
            continue
        if token in known:
            return token

    if fallback_extractor is not None:
        fallback = fallback_extractor(raw, default).upper().replace("USDT", "").replace("USD", "")
        if fallback in known:
            return fallback
    return default


def _estimate_news_bias(headlines: list[str]) -> tuple[str, str]:
    positive_terms = {
        "APPROVAL", "APPROVE", "INFLOW", "SURGE", "SOAR", "RALLY",
        "PARTNERSHIP", "ADOPTION", "BUY", "ACCUMULATION", "UPGRADE",
    }
    negative_terms = {
        "HACK", "EXPLOIT", "LAWSUIT", "BAN", "OUTFLOW", "PLUNGE",
        "SELL-OFF", "SELLOFF", "LIQUIDATION", "CRACKDOWN", "DROP",
    }
    pos = 0
    neg = 0
    for headline in headlines:
        upper = str(headline or "").upper()
        pos += sum(1 for term in positive_terms if term in upper)
        neg += sum(1 for term in negative_terms if term in upper)
    if pos > neg:
        return "bullish", "positive"
    if neg > pos:
        return "bearish", "negative"
    return "mixed", "mixed"


def _score_news_watch_article(article: dict, symbol: str, *, aliases: list[str] | None = None) -> tuple[int, list[str]]:
    title = str(article.get("title") or "")
    summary = str(article.get("summary") or "")
    haystack = f"{title} {summary}".upper()
    score = 0
    reasons: list[str] = []

    symbol_aliases = aliases or _news_watch_aliases(symbol)
    if any(alias in haystack for alias in symbol_aliases):
        score += 3
        reasons.append("symbol match")

    high_impact_keywords = {
        "ETF": 3,
        "SEC": 3,
        "APPROVAL": 3,
        "APPROVE": 3,
        "HACK": 4,
        "LAWSUIT": 3,
        "BAN": 3,
        "LIQUIDATION": 4,
        "BANKRUPTCY": 4,
        "WHALE": 2,
        "FED": 2,
        "RATE CUT": 2,
        "RATE HIKE": 2,
        "INFLATION": 2,
        "CPI": 2,
        "PCE": 2,
        "FOMC": 2,
        "BREAKING": 2,
        "SURGE": 2,
        "PLUNGE": 2,
        "PLUNGES": 2,
        "SOAR": 2,
        "COLLAPSE": 3,
        "DELIST": 3,
        "LISTING": 2,
        "PARTNERSHIP": 1,
        "EARNINGS": 2,
    }
    for keyword, weight in high_impact_keywords.items():
        if keyword in haystack:
            score += weight
            reasons.append(keyword.lower())

    return score, reasons


def _score_news_watch_article_for_chat_server(
    article: dict,
    symbol: str,
    *,
    alias_builder: Callable[[str], list[str]],
) -> tuple[int, list[str]]:
    return _score_news_watch_article(article, symbol, aliases=alias_builder(symbol))


def _make_news_watch_hash(article: dict) -> str:
    raw = "||".join(
        [
            str(article.get("link") or "").strip(),
            str(article.get("title") or "").strip(),
            str(article.get("published") or "").strip(),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()
