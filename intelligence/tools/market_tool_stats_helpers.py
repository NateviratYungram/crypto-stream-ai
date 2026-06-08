from __future__ import annotations

from typing import List


def _calculate_hurst_exponent(prices: List[float], max_lag: int = 20) -> float:
    """Estimate Hurst Exponent to detect trend persistence vs mean reversion."""
    import numpy as np

    try:
        if len(prices) < max_lag * 2:
            return 0.5
        valid_pairs = []
        for lag in range(2, max_lag):
            value = np.sqrt(np.std(np.subtract(prices[lag:], prices[:-lag])))
            if np.isfinite(value) and value > 0:
                valid_pairs.append((lag, value))
        if len(valid_pairs) < 2:
            return 0.5
        log_lags = np.log([lag for lag, _ in valid_pairs])
        log_tau = np.log([value for _, value in valid_pairs])
        reg = np.polyfit(log_lags, log_tau, 1)
        return reg[0] * 2.0
    except Exception:
        return 0.5


def _calculate_volatility_skew(prices: List[float]) -> float:
    """Measure return skewness to detect asymmetric risk."""
    import numpy as np
    from scipy.stats import skew

    try:
        if len(prices) < 20:
            return 0.0
        returns = np.diff(np.log(prices))
        return float(skew(returns))
    except Exception:
        return 0.0


def _get_historical_stock_universe(
    universe: str,
    nasdaq_100_tickers: list[str],
    sp500_tickers: list[str],
) -> tuple[str, list[str]]:
    normalized = str(universe or "COMBINED").upper().strip()
    if normalized == "NASDAQ100":
        return "NASDAQ100", list(dict.fromkeys(list(nasdaq_100_tickers)))
    if normalized == "SP500":
        return "SP500", list(dict.fromkeys(list(sp500_tickers)))
    return "COMBINED", list(dict.fromkeys(list(nasdaq_100_tickers) + list(sp500_tickers)))
