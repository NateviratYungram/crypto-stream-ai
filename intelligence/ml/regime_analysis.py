import numpy as np
import logging

logger = logging.getLogger(__name__)

def estimate_hurst_exponent(ts: np.ndarray) -> float:
    """
    Estimates the Hurst Exponent (H) of a time series.
    H < 0.5: Mean-reverting (Anti-persistent)
    H = 0.5: Random Walk (Brownian motion)
    H > 0.5: Trending (Persistent)
    """
    try:
        if len(ts) < 100:
            return 0.5 # Not enough data for a stable estimate

        # Calculate the log-returns
        lags = range(2, 50)
        tau = [np.sqrt(np.std(np.subtract(ts[lag:], ts[:-lag]))) for lag in lags]

        # Calculate the slope of the log-log plot to find the Hurst Exponent
        poly = np.polyfit(np.log(lags), np.log(tau), 1)

        # The relationship is std(ts(t+tau) - ts(t)) ~ tau^H
        # Our tau calculation above is effectively tau^(H/2) because of the sqrt(std)
        # So we multiply poly[0] by 2.0
        hurst = poly[0] * 2.0

        return float(np.clip(hurst, 0.0, 1.0))
    except Exception as e:
        logger.warning(f"Hurst Estimation failed: {e}")
        return 0.5
