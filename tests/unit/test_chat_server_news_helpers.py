from chat_server_news_helpers import (
    _estimate_news_bias,
    _extract_news_watch_symbol,
    _make_news_watch_hash,
    _news_watch_aliases,
    _score_news_watch_article,
    _score_news_watch_article_for_chat_server,
)


def test_news_watch_aliases_expand_known_symbols():
    btc_aliases = _news_watch_aliases("btcusd")
    sp500_aliases = _news_watch_aliases("sp500")
    eth_aliases = _news_watch_aliases("eth")
    sol_aliases = _news_watch_aliases("sol")
    gold_aliases = _news_watch_aliases("xauusd")
    nasdaq_aliases = _news_watch_aliases("ndx")

    assert "BTC" in btc_aliases
    assert "BITCOIN" in btc_aliases
    assert "BTCUSD" in btc_aliases
    assert "SP500" in sp500_aliases
    assert "SPX" in sp500_aliases
    assert "ETHEREUM" in eth_aliases
    assert "SOLANA" in sol_aliases
    assert "XAU" in gold_aliases
    assert "NASDAQ" in nasdaq_aliases


def test_extract_news_watch_symbol_prefers_category_alias_token_and_fallback():
    assert _extract_news_watch_symbol("show crypto headlines") == "BTC"
    assert _extract_news_watch_symbol("stock market alert please") == "SP500"
    assert _extract_news_watch_symbol("latest forex alert") == "EURUSD"
    assert _extract_news_watch_symbol("breaking on XAUUSD right now") == "GOLD"
    assert _extract_news_watch_symbol("watch BNB news", trade_symbol_aliases={"BNB": ["BINANCECOIN"]}) == "BNB"
    assert (
        _extract_news_watch_symbol(
            "notify me about the market",
            default="ETH",
            fallback_extractor=lambda raw, default: "ETHUSD",
        )
        == "ETH"
    )


def test_extract_news_watch_symbol_falls_back_to_default_for_noise():
    assert (
        _extract_news_watch_symbol(
            "please watch the latest headlines",
            default="SOL",
            fallback_extractor=lambda raw, default: "UNKNOWN",
        )
        == "SOL"
    )


def test_estimate_news_bias_reports_bullish_bearish_and_mixed():
    assert _estimate_news_bias(["ETF approval sparks rally and inflow"]) == ("bullish", "positive")
    assert _estimate_news_bias(["Hack and lawsuit trigger plunge"]) == ("bearish", "negative")
    assert _estimate_news_bias(["Adoption grows but ban fears remain"]) == ("mixed", "mixed")


def test_score_news_watch_article_and_hash_are_stable():
    article = {
        "title": "Bitcoin ETF approval sparks whale surge",
        "summary": "SEC approval sends BTC higher",
        "link": "https://example.com/a",
        "published": "2026-06-02T00:00:00Z",
    }

    score, reasons = _score_news_watch_article(article, "BTC", aliases=["BTC", "BITCOIN"])
    article_hash = _make_news_watch_hash(article)

    assert score >= 11
    assert "symbol match" in reasons
    assert "etf" in reasons
    assert "approval" in reasons
    assert "whale" in reasons
    assert article_hash == _make_news_watch_hash(dict(article))


def test_score_news_watch_article_uses_default_aliases_and_wrapper():
    article = {"title": "NASDAQ earnings beat expectations", "summary": "index may soar"}

    direct_score, direct_reasons = _score_news_watch_article(article, "NASDAQ")
    wrapped_score, wrapped_reasons = _score_news_watch_article_for_chat_server(
        article,
        "NASDAQ",
        alias_builder=lambda symbol: ["NASDAQ", "NASDAQ 100"],
    )

    assert direct_score >= 5
    assert "symbol match" in direct_reasons
    assert "earnings" in direct_reasons
    assert wrapped_score == direct_score
    assert wrapped_reasons == direct_reasons
