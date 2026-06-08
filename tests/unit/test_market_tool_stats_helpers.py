from intelligence.tools.market_tool_stats_helpers import (
    _calculate_hurst_exponent,
    _calculate_volatility_skew,
    _get_historical_stock_universe,
)


def test_calculate_hurst_exponent_returns_default_for_short_or_bad_input():
    assert _calculate_hurst_exponent([1, 2, 3], max_lag=5) == 0.5
    assert _calculate_hurst_exponent(["bad"] * 50) == 0.5
    assert _calculate_hurst_exponent([5.0] * 50, max_lag=10) == 0.5


def test_calculate_hurst_exponent_returns_float_for_trend_series():
    prices = [100 + i * 0.3 + ((-1) ** i) * 0.2 for i in range(100)]
    value = _calculate_hurst_exponent(prices, max_lag=10)

    assert isinstance(value, float)


def test_calculate_hurst_exponent_handles_polyfit_failure(monkeypatch):
    import numpy as np

    monkeypatch.setattr(np, "polyfit", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad fit")))

    prices = [100 + i * 0.3 + ((-1) ** i) * 0.2 for i in range(100)]
    assert _calculate_hurst_exponent(prices, max_lag=10) == 0.5


def test_calculate_volatility_skew_handles_short_and_valid_series():
    assert _calculate_volatility_skew([1, 2, 3]) == 0.0
    value = _calculate_volatility_skew([100 + ((-1) ** i) * i for i in range(1, 40)])

    assert isinstance(value, float)


def test_calculate_volatility_skew_returns_default_on_failure(monkeypatch):
    import scipy.stats

    monkeypatch.setattr(scipy.stats, "skew", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad skew")))

    assert _calculate_volatility_skew([100 + i for i in range(40)]) == 0.0


def test_get_historical_stock_universe_resolves_and_deduplicates():
    nasdaq = ["NVDA", "MSFT", "NVDA"]
    sp500 = ["AAPL", "MSFT"]

    assert _get_historical_stock_universe("NASDAQ100", nasdaq, sp500) == ("NASDAQ100", ["NVDA", "MSFT"])
    assert _get_historical_stock_universe("SP500", nasdaq, sp500) == ("SP500", ["AAPL", "MSFT"])
    assert _get_historical_stock_universe("combined", nasdaq, sp500) == ("COMBINED", ["NVDA", "MSFT", "AAPL"])
