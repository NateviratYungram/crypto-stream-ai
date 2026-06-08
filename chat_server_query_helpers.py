from __future__ import annotations

import re
import unicodedata


def _normalize_query_text(text: str) -> str:
    cleaned = unicodedata.normalize("NFKC", str(text or "")).replace("\u200b", "").lower()
    replacements = {
        "เธซเนเธธเธ": "เธซเธธเนเธ",
        "เธเธฑเธญเธ”เธน": "เธเธญเธ”เธน",
        "เธเนเธญเธ”เธน": "เธเธญเธ”เธน",
        "เนเธ10เธเธต": "เนเธ10เธเธต",
    }
    for src, dst in replacements.items():
        cleaned = cleaned.replace(src, dst)
    return cleaned


def _extract_historical_years(text: str, default: int = 10) -> int:
    cleaned = _normalize_query_text(text)
    if "decade" in cleaned:
        return 10
    match = re.search(r"(\d+)\s*(?:-|โ€“)?\s*(?:เธเธต|year|years|yr|yrs|y)", cleaned)
    if match:
        try:
            return max(1, min(int(match.group(1)), 15))
        except Exception:
            pass
    return default


def _extract_index_history_targets(text: str) -> list[str]:
    cleaned = _normalize_query_text(text)
    targets: list[str] = []
    alias_groups = [
        ("NASDAQ_100", ["nasdaq 100", "nasdaq100", "ndx", "us100", "nas100"]),
        ("SP500", ["s&p 500", "s&p500", "sp500", "spx", "us500"]),
        ("NASDAQ_COMPOSITE", ["nasdaq composite", "ixic"]),
    ]
    for canonical, aliases in alias_groups:
        if any(alias in cleaned for alias in aliases):
            targets.append(canonical)

    broad_index_terms = [
        "เธ”เธฑเธเธเธต", "index", "indices", "เธ เธฒเธเธฃเธงเธกเธ•เธฅเธฒเธ”เธซเธธเนเธ", "us index", "เธ•เธฅเธฒเธ”เธซเธธเนเธเธชเธซเธฃเธฑเธ", "เธ•เธฅเธฒเธ”เธซเธธเนเธเธญเน€เธกเธฃเธดเธเธฒ",
    ]
    if not targets and any(term in cleaned for term in broad_index_terms):
        return ["NASDAQ_100", "SP500", "NASDAQ_COMPOSITE"]
    return targets


def _is_broad_stock_history_query(text: str) -> bool:
    cleaned = _normalize_query_text(text)
    stock_terms = [
        "เธซเธธเนเธ", "stock", "stocks", "equity", "equities", "เธ•เธฅเธฒเธ”เธซเธธเนเธ", "เธ”เธฑเธเธเธตเธซเธธเนเธ",
        "us market", "เธ•เธฅเธฒเธ”เธซเธธเนเธเธชเธซเธฃเธฑเธ", "เธ•เธฅเธฒเธ”เธซเธธเนเธเธญเน€เธกเธฃเธดเธเธฒ",
    ]
    history_terms = [
        "เธขเนเธญเธเธซเธฅเธฑเธ", "เธ—เธตเนเธเนเธฒเธเธกเธฒ", "historical", "history", "return", "performance",
        "1 เธเธต", "3 เธเธต", "5 เธเธต", "10 เธเธต", "1เธเธต", "3เธเธต", "5เธเธต", "10เธเธต",
        "year", "years", "1yr", "one year", "12 เน€เธ”เธทเธญเธ", "12เน€เธ”เธทเธญเธ",
        "เธเนเธญเธกเธนเธฅ 1เธเธต", "เธเนเธญเธกเธนเธฅ 1 เธเธต",
    ]
    disqualifiers = [
        "crypto", "เธเธฃเธดเธเนเธ•", "coin", "เน€เธซเธฃเธตเธขเธ", "btc", "eth", "sol", "xrp", "bnb",
        "เธ—เธญเธ", "gold", "xau", "xauusd", "oil", "เธเนเธณเธกเธฑเธ", "forex", "เธเนเธฒเน€เธเธดเธ", "eurusd", "gbpusd",
    ]
    return (
        any(term in cleaned for term in stock_terms)
        and any(term in cleaned for term in history_terms)
        and not any(term in cleaned for term in disqualifiers)
    )


def _is_capability_question(text: str) -> bool:
    cleaned = _normalize_query_text(text)
    capability_terms = [
        "เนเธ”เนเนเธซเธก", "เนเธ”เนเธกเธฑเนเธข", "เธ—เธณเนเธ”เนเนเธซเธก", "เธ—เธณเนเธ”เนเธกเธฑเนเธข", "เธ•เธญเธเนเธ”เนเนเธซเธก", "เธ•เธญเธเนเธ”เนเธกเธฑเนเธข",
        "can you", "could you", "are you able to", "do you support",
    ]
    if any(term in cleaned for term in capability_terms):
        return True
    finance_terms = ["เธซเธธเนเธ", "stock", "stocks", "nasdaq", "s&p", "sp500", "market", "เธเนเธญเธกเธนเธฅ"]
    soft_question_markers = ["เนเธซเธก", "เธกเธฑเนเธข", "?", "เธ–เนเธฒเธญเธขเธฒเธ", "เธญเธขเธฒเธเธฃเธนเน"]
    return any(term in cleaned for term in finance_terms) and any(term in cleaned for term in soft_question_markers)


def _is_stock_top_performer_history_question(text: str) -> bool:
    cleaned = _normalize_query_text(text)
    stock_terms = ["เธซเธธเนเธ", "stock", "stocks", "nasdaq", "s&p", "sp500", "equity", "equities"]
    ranking_terms = [
        "top 10", "10 เธ•เธฑเธง", "10เธ•เธฑเธง", "10 เธ•เธฑเธงเนเธฃเธ", "10เธ•เธฑเธงเนเธฃเธ", "10 เธญเธฑเธเธ”เธฑเธ", "10เธญเธฑเธเธ”เธฑเธ", "เธเธถเนเธเธกเธฒเธเธ—เธตเนเธชเธธเธ”", "เธเธถเนเธเน€เธขเธญเธฐเธ—เธตเนเธชเธธเธ”",
        "เธฅเธเธกเธฒเธเธ—เธตเนเธชเธธเธ”", "เธฅเธเน€เธขเธญเธฐเธ—เธตเนเธชเธธเธ”", "เธ•เธเธกเธฒเธเธ—เธตเนเธชเธธเธ”", "เนเธขเนเธ—เธตเนเธชเธธเธ”",
        "best performing", "top performing", "top gainers", "worst performing", "top losers", "bottom 10",
        "เธญเธฑเธเธ”เธฑเธเธ•เนเธ", "เธเธฅเธ•เธญเธเนเธ—เธเธ”เธตเธ—เธตเนเธชเธธเธ”", "เธ•เธฑเธงเนเธฃเธเธ—เธตเนเธเธถเนเธเธกเธฒเธเธ—เธตเนเธชเธธเธ”", "เธ•เธฑเธงเนเธฃเธเธ—เธตเนเธฅเธเธกเธฒเธเธ—เธตเนเธชเธธเธ”",
    ]
    history_terms = [
        "10 เธเธต", "10เธเธต", "เธขเนเธญเธเธซเธฅเธฑเธ", "เธ—เธตเนเธเนเธฒเธเธกเธฒ", "เนเธ10เธเธต", "เนเธ 10 เธเธต", "10-year", "10 year", "ten years", "historical",
    ]
    disqualifiers = ["crypto", "เธเธฃเธดเธเนเธ•", "เน€เธซเธฃเธตเธขเธ", "coin", "btc", "eth", "เธ—เธญเธ", "gold", "xau", "oil", "forex"]
    return (
        any(term in cleaned for term in stock_terms)
        and any(term in cleaned for term in ranking_terms)
        and any(term in cleaned for term in history_terms)
        and not any(term in cleaned for term in disqualifiers)
    )


def _extract_stock_history_direction(text: str) -> str:
    cleaned = _normalize_query_text(text)
    loser_terms = ["เธฅเธเธกเธฒเธเธ—เธตเนเธชเธธเธ”", "เธฅเธเน€เธขเธญเธฐเธ—เธตเนเธชเธธเธ”", "worst", "loser", "losers", "down the most", "bottom 10", "เธ•เธเธกเธฒเธเธ—เธตเนเธชเธธเธ”", "เนเธขเนเธ—เธตเนเธชเธธเธ”"]
    return "bottom" if any(term in cleaned for term in loser_terms) else "top"


def _extract_stock_history_universe(text: str) -> str:
    cleaned = _normalize_query_text(text)
    asks_nasdaq = "nasdaq 100" in cleaned or "nasdaq100" in cleaned
    asks_sp500 = "s&p 500" in cleaned or "s&p500" in cleaned or "sp500" in cleaned
    if asks_nasdaq and not asks_sp500:
        return "NASDAQ100"
    if asks_sp500 and not asks_nasdaq:
        return "SP500"
    return "COMBINED"


def _is_ranked_stock_history_query(text: str) -> bool:
    cleaned = _normalize_query_text(text)
    stock_terms = [
        "stock", "stocks", "equity", "equities", "nasdaq", "s&p", "sp500",
        "เธซเธธเนเธ", "เธซเนเธธเธ", "เธ•เธฅเธฒเธ”เธซเธธเนเธ",
    ]
    ranking_terms = [
        "top 10", "bottom 10", "best performing", "top performing", "worst performing",
        "top gainers", "top losers", "highest return", "highest returns", "best return", "best returns",
        "10 เธญเธฑเธเธ”เธฑเธ", "10 เธ•เธฑเธง", "เธญเธฑเธเธ”เธฑเธ", "เธเธฅเธ•เธญเธเนเธ—เธเธชเธนเธเธชเธธเธ”", "เธเธฅเธ•เธญเธเนเธ—เธเธ”เธตเธ—เธตเนเธชเธธเธ”", "เธเธถเนเธเธกเธฒเธเธ—เธตเนเธชเธธเธ”", "เธฅเธเธกเธฒเธเธ—เธตเนเธชเธธเธ”",
    ]
    history_terms = [
        "historical", "history", "เธขเนเธญเธเธซเธฅเธฑเธ", "เธ—เธตเนเธเนเธฒเธเธกเธฒ",
        "1 year", "1-year", "one year", "3 year", "3-year", "three years",
        "5 year", "5-year", "five years", "10 year", "10-year", "ten years",
        "1 เธเธต", "1เธเธต", "3 เธเธต", "3เธเธต", "5 เธเธต", "5เธเธต", "10 เธเธต", "10เธเธต",
    ]
    disqualifiers = [
        "crypto", "coin", "btc", "eth", "sol", "xrp", "bnb",
        "เธเธฃเธดเธเนเธ•", "เน€เธซเธฃเธตเธขเธ", "gold", "xau", "oil", "forex",
    ]
    return (
        any(term in cleaned for term in stock_terms)
        and any(term in cleaned for term in ranking_terms)
        and any(term in cleaned for term in history_terms)
        and not any(term in cleaned for term in disqualifiers)
    )


def _is_explicit_stock_ranking_request(text: str) -> bool:
    raw = str(text or "").lower()
    has_stock = any(term in raw for term in ["เธซเธธเนเธ", "เธซเนเธธเธ", "stock", "stocks", "equity", "equities"])
    has_rank = any(term in raw for term in [
        "เธญเธฑเธเธ”เธฑเธ", "10 เธญเธฑเธเธ”เธฑเธ", "10เธญเธฑเธเธ”เธฑเธ", "10 เธ•เธฑเธง", "10เธ•เธฑเธง", "top 10", "highest return",
        "best return", "best performing", "top performing", "เธเธฅเธ•เธญเธเนเธ—เธเธชเธนเธเธชเธธเธ”", "เธเธฅเธ•เธญเธเนเธ—เธเธ”เธตเธ—เธตเนเธชเธธเธ”",
        "เธเธถเนเธเธกเธฒเธเธ—เธตเนเธชเธธเธ”", "เธฅเธเธกเธฒเธเธ—เธตเนเธชเธธเธ”",
    ])
    has_period = any(term in raw for term in [
        "1 เธเธต", "1เธเธต", "3 เธเธต", "3เธเธต", "5 เธเธต", "5เธเธต", "10 เธเธต", "10เธเธต",
        "1 year", "3 year", "5 year", "10 year", "1-year", "3-year", "5-year", "10-year",
        "เธขเนเธญเธเธซเธฅเธฑเธ", "เธ—เธตเนเธเนเธฒเธเธกเธฒ",
    ])
    has_non_stock_asset = any(term in raw for term in [
        "crypto", "coin", "btc", "eth", "sol", "xrp", "bnb", "เธเธฃเธดเธเนเธ•", "เน€เธซเธฃเธตเธขเธ",
        "gold", "xau", "oil", "forex",
    ])
    return has_stock and has_rank and has_period and not has_non_stock_asset
