from intelligence.tools.market_tool_fundamentals_helpers import _summarize_stock_fundamentals


def test_summarize_stock_fundamentals_returns_empty_without_price():
    assert _summarize_stock_fundamentals("AAPL", {}, {}) == {}


def test_summarize_stock_fundamentals_builds_core_payload_and_targets():
    result = _summarize_stock_fundamentals(
        "AAPL",
        {
            "longName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "marketCap": 3_000_000_000_000,
            "currentPrice": 200.0,
            "trailingPE": 14.2,
            "forwardPE": 13.1,
            "priceToBook": 10.0,
            "priceToSalesTrailing12Months": 7.5,
            "trailingEps": 6.12,
            "earningsGrowth": 0.2,
            "revenueGrowth": 0.1,
            "profitMargins": 0.25,
            "returnOnEquity": 0.3,
            "debtToEquity": 1.5,
            "fiftyTwoWeekLow": 150.0,
            "fiftyTwoWeekHigh": 250.0,
            "targetMeanPrice": 230.0,
            "numberOfAnalystOpinions": 30,
        },
    )

    assert result["company"] == "Apple Inc."
    assert result["market_cap_b"] == 3000.0
    assert result["pe_signal"] == "CHEAP"
    assert result["range_pct"] == 50.0
    assert result["range_signal"] == "MID_RANGE"
    assert result["analyst_upside_pct"] == 15.0
    assert result["sell_targets"]["T1_analyst_target"] == 230.0
    assert result["sell_targets"]["T3_52w_high_resistance"] == 250.0
    assert len(result["sell_logic"]) >= 3


def test_summarize_stock_fundamentals_uses_sqlite_fallbacks_and_above_target_paths():
    result = _summarize_stock_fundamentals(
        "TSLA",
        {
            "regularMarketPrice": 110.0,
            "targetMeanPrice": 100.0,
            "numberOfAnalystOpinions": 12,
            "fiftyTwoWeekLow": 80.0,
        },
        {"pct_52wh_sq": 10.0},
    )

    assert result["company"] == "TSLA"
    assert result["analyst_upside_pct"] == -9.1
    assert "already above the analyst target" in result["sell_logic"][0]
    assert result["52w_high"] is not None


def test_summarize_stock_fundamentals_handles_price_discovery_and_na_growth():
    result = _summarize_stock_fundamentals(
        "NVDA",
        {
            "currentPrice": 300.0,
            "fiftyTwoWeekLow": 100.0,
            "fiftyTwoWeekHigh": 250.0,
            "targetMeanPrice": 330.0,
        },
    )

    assert result["eps_growth_yoy"] == "N/A"
    assert result["sell_targets"]["T3_52w_high_resistance"] == 250.0
    assert "price discovery" in result["sell_logic"][-1].lower()


def test_summarize_stock_fundamentals_covers_expensive_and_unknown_range_paths():
    result = _summarize_stock_fundamentals(
        "NFLX",
        {
            "currentPrice": 500.0,
            "trailingPE": 30.0,
            "forwardPE": 24.0,
            "fiftyTwoWeekHigh": 600.0,
        },
    )

    assert result["pe_signal"] == "EXPENSIVE"
    assert result["range_signal"] == "UNKNOWN"
    assert result["sell_targets"]["T3_52w_high_resistance"] == 600.0


def test_summarize_stock_fundamentals_uses_fallback_price_without_targets():
    result = _summarize_stock_fundamentals(
        "META",
        {"trailingPE": 20.0, "fiftyTwoWeekLow": 90.0, "fiftyTwoWeekHigh": 120.0},
        {"price_sq": 100.0},
    )

    assert result["current_price"] == 100.0
    assert result["pe_signal"] == "FAIR"
    assert result["analyst_target"] is None
    assert result["sell_logic"] == ["TP3: $120.00 is the prior 52-week high resistance zone."]


def test_summarize_stock_fundamentals_skips_52w_logic_when_high_missing():
    result = _summarize_stock_fundamentals(
        "AMD",
        {
            "currentPrice": 150.0,
            "trailingPE": 18.0,
            "targetMeanPrice": 175.0,
            "numberOfAnalystOpinions": 20,
        },
    )

    assert result["52w_high"] is None
    assert "T3_52w_high_resistance" not in result["sell_targets"]
    assert len(result["sell_logic"]) == 2


def test_summarize_stock_fundamentals_skips_52w_upside_when_price_is_non_positive():
    result = _summarize_stock_fundamentals(
        "SHOP",
        {
            "regularMarketPrice": -1.0,
            "fiftyTwoWeekHigh": 110.0,
        },
    )

    assert result["sell_targets"]["T3_52w_high_resistance"] == 110.0
    assert "T3_upside_pct" not in result["sell_targets"]
    assert "prior 52-week high resistance zone" in result["sell_logic"][-1]
