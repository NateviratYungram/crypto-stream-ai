from intelligence.tools.market_tool_opportunity_helpers import (
    _absolute_change,
    _build_opportunity_group,
    _enrich_opportunity_stock,
    _liquid_stocks,
    _parse_volume,
)


def test_parse_volume_handles_numeric_suffixes_and_bad_values():
    assert _parse_volume(123) == 123.0
    assert _parse_volume("1.5M") == 1_500_000.0
    assert _parse_volume("250K") == 250_000.0
    assert _parse_volume("N/A") == 0.0
    assert _parse_volume("bad") == 0.0
    assert _parse_volume(None) == 0.0


def test_liquid_stocks_filters_by_min_volume():
    stocks = [
        {"symbol": "AAA", "volume": "499K"},
        {"symbol": "BBB", "volume": "0.6M"},
        {"symbol": "CCC", "volume": 900_000},
    ]

    result = _liquid_stocks(stocks, min_volume=500_000)

    assert [row["symbol"] for row in result] == ["BBB", "CCC"]


def test_absolute_change_handles_percent_variants_and_bad_data():
    assert _absolute_change({"change_percent": "-4.2%"}) == 4.2
    assert _absolute_change({"percent_change": 3.5}) == 3.5
    assert _absolute_change({"change_percent": "bad"}) == 0.0


def test_enrich_opportunity_stock_adds_group_and_news():
    enriched = _enrich_opportunity_stock(
        {"symbol": "NVDA", "exchange": "NASDAQ"},
        "NASDAQ 100",
        fetch_news=True,
        news_fetcher=lambda symbol: [{"title": f"{symbol} headline 1"}, {"title": "headline 2"}],
    )

    assert enriched["group"] == "NASDAQ 100"
    assert enriched["news_headlines"] == ["NVDA headline 1", "headline 2"]


def test_enrich_opportunity_stock_handles_empty_and_fetch_errors():
    assert _enrich_opportunity_stock(None, "CRYPTO") is None

    enriched = _enrich_opportunity_stock(
        {"symbol": "BTC", "exchange": "BINANCE"},
        "CRYPTO",
        fetch_news=True,
        news_fetcher=lambda symbol: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert enriched["news_headlines"] == ["News unavailable."]


def test_build_opportunity_group_sets_hero_from_gainer_or_loser():
    group = _build_opportunity_group(
        "S&P 500",
        [{"symbol": "AAPL", "exchange": "NASDAQ"}],
        [{"symbol": "TSLA", "exchange": "NASDAQ"}],
    )
    loser_only = _build_opportunity_group(
        "CRYPTO",
        [],
        [{"symbol": "ETH", "exchange": "BINANCE"}],
    )

    assert group["hero_symbol"] == "AAPL"
    assert group["top_loser"]["symbol"] == "TSLA"
    assert loser_only["hero_symbol"] == "ETH"
