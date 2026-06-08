from __future__ import annotations

from typing import Any, Callable, Iterable, Optional


def _parse_volume(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("N/A", "0")
        if "M" in cleaned:
            return float(cleaned.replace("M", "")) * 1_000_000
        if "K" in cleaned:
            return float(cleaned.replace("K", "")) * 1_000
        try:
            return float(cleaned)
        except Exception:
            return 0.0
    return 0.0


def _liquid_stocks(stocks: Iterable[dict[str, Any]], min_volume: float = 500_000) -> list[dict[str, Any]]:
    return [stock for stock in stocks if _parse_volume(stock.get("volume", 0)) >= min_volume]


def _absolute_change(stock: dict[str, Any]) -> float:
    try:
        raw = stock.get("change_percent") or stock.get("percent_change") or 0
        return abs(float(str(raw).replace("%", "")))
    except Exception:
        return 0.0


def _enrich_opportunity_stock(
    stock: Optional[dict[str, Any]],
    group_name: str,
    *,
    fetch_news: bool = False,
    news_fetcher: Optional[Callable[[str], list[dict[str, Any]]]] = None,
) -> Optional[dict[str, Any]]:
    if not stock:
        return None

    enriched = dict(stock)
    enriched["group"] = group_name
    if fetch_news:
        try:
            articles = news_fetcher(enriched["symbol"]) if news_fetcher else []
            enriched["news_headlines"] = [article["title"] for article in articles[:3]] or ["No news found."]
        except Exception:
            enriched["news_headlines"] = ["News unavailable."]
    return enriched


def _build_opportunity_group(
    name: str,
    gainers: list[dict[str, Any]],
    losers: list[dict[str, Any]],
    *,
    fetch_news: bool = False,
    news_fetcher: Optional[Callable[[str], list[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    top_gainer = _enrich_opportunity_stock(
        gainers[0] if gainers else None,
        name,
        fetch_news=fetch_news,
        news_fetcher=news_fetcher,
    )
    top_loser = _enrich_opportunity_stock(
        losers[0] if losers else None,
        name,
        fetch_news=fetch_news,
        news_fetcher=news_fetcher,
    )
    return {
        "group_name": name,
        "top_gainer": top_gainer,
        "top_loser": top_loser,
        "hero_symbol": top_gainer["symbol"] if top_gainer else (top_loser["symbol"] if top_loser else None),
        "hero_exchange": top_gainer["exchange"] if top_gainer else (top_loser["exchange"] if top_loser else None),
    }
