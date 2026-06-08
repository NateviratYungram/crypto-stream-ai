from intelligence.tools.market_tool_response_helpers import (
    _build_market_features_response,
    _build_market_opportunities_response,
    _interpret_market_features,
    _select_market_opportunity_heroes,
)


def test_select_market_opportunity_heroes_uses_priority_order():
    groups = {
        "CRYPTO": {"top_gainer": {"symbol": "BTC", "exchange": "BINANCE"}},
        "SP500": {
            "top_gainer": {"symbol": "AAPL", "exchange": "NASDAQ"},
            "top_loser": {"symbol": "TSLA", "exchange": "NASDAQ"},
        },
    }

    heroes = _select_market_opportunity_heroes(groups)

    assert heroes["hero_symbol"] == "AAPL"
    assert heroes["hero_exchange"] == "NASDAQ"
    assert heroes["hero_loser"] == "TSLA"


def test_select_market_opportunity_heroes_falls_back_to_loser_when_needed():
    groups = {
        "CRYPTO": {"top_loser": {"symbol": "ETH", "exchange": "BINANCE"}},
    }

    heroes = _select_market_opportunity_heroes(groups)

    assert heroes["hero_symbol"] is None
    assert heroes["hero_loser"] == "ETH"
    assert heroes["hero_loser_exchange"] == "BINANCE"


def test_build_market_opportunities_response_embeds_groups_and_instruction():
    response = _build_market_opportunities_response(
        fetched_at="2026-05-26 10:00 UTC",
        groups={
            "NASDAQ_100": {"top_gainer": {"symbol": "NVDA", "exchange": "NASDAQ"}},
            "SP500": {"top_loser": {"symbol": "MSFT", "exchange": "NASDAQ"}},
        },
    )

    assert response["data_source"] == "Yahoo Finance Screener (realtime)"
    assert response["fetched_at"] == "2026-05-26 10:00 UTC"
    assert response["groups"]["NASDAQ_100"]["top_gainer"]["symbol"] == "NVDA"
    assert response["hero_symbol"] == "NVDA"
    assert response["hero_loser"] == "MSFT"
    assert "CRITICAL PRESENTATION RULES" in response["instruction"]


def test_interpret_market_features_builds_plain_language_summary():
    text = _interpret_market_features(
        {
            "return_30d": 0.123,
            "volatility_30d": 0.35,
            "corr_vs_sp500_30d": 0.82,
            "beta_vs_sp500": 1.4,
            "rel_strength_30d": -0.056,
        },
        "NVDA",
    )

    assert "NVDA returned +12.3% over the past 30 days" in text
    assert "is moderately volatile (35% annualized vol)" in text
    assert "strongly correlated with SP500 (r=0.82 over 30d)" in text
    assert "beta vs SP500 = 1.40 (more risky than market)" in text
    assert "underperformed SP500 by 5.6pp over 30d." in text


def test_interpret_market_features_handles_missing_data():
    assert _interpret_market_features({}, "BTC") == "Insufficient data for interpretation."


def test_build_market_features_response_formats_sections_and_interpretation():
    response = _build_market_features_response(
        symbol="btc",
        computed_date="2026-06-02T00:00:00+00:00",
        row={
            "return_1d": 0.01,
            "return_7d": None,
            "return_30d": 0.05,
            "return_90d": -0.02,
            "return_365d": 0.5,
            "volatility_7d": 0.1,
            "volatility_30d": 0.25,
            "volatility_90d": None,
            "corr_vs_sp500_30d": 0.4,
            "corr_vs_sp500_90d": None,
            "corr_vs_btc_30d": 1.0,
            "corr_vs_btc_90d": 0.95,
            "corr_vs_gold_30d": -0.2,
            "beta_vs_sp500": 1.2,
            "pct_from_52w_high": -8.4,
            "pct_from_52w_low": 37.9,
            "rel_strength_30d": 0.03,
        },
        interpret_features_fn=lambda row, symbol: f"interp:{symbol}:{row['return_30d']}",
    )

    assert response["symbol"] == "BTC"
    assert response["as_of"] == "2026-06-02T00:00:00+00:00"
    assert response["returns"]["1d"] == "+1.00%"
    assert response["returns"]["7d"] == "N/A"
    assert response["returns"]["1y"] == "+50.00%"
    assert response["volatility_annualized"]["30d"] == "+25.00%"
    assert response["correlation"]["vs_gold_30d"] == "-0.20"
    assert response["beta_vs_sp500"] == "1.20"
    assert response["price_position"]["pct_from_52w_high"] == "-8.4%"
    assert response["price_position"]["pct_from_52w_low"] == "+37.9%"
    assert response["relative_strength_vs_sp500_30d"] == "+3.00%"
    assert response["interpretation"] == "interp:btc:0.05"
