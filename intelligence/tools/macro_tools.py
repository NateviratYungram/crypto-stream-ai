import logging
from typing import Any, Dict

import yfinance as yf

logger = logging.getLogger(__name__)

def get_macro_risk_data() -> Dict[str, Any]:
    """
    Fetches real-time Volatility Index (VIX) and US Dollar Index (DXY).
    Used as a safety shield to scale down trade sizes during extreme uncertainty.
    """
    try:
        # VIX: Global Fear Gauge
        vix_ticker = yf.Ticker('^VIX')
        vix_hist = vix_ticker.history(period='1d')
        vix_val = vix_hist['Close'].iloc[-1] if not vix_hist.empty else 15.0

        # DXY: Dollar Strength (Critical for GOLD/Forex)
        dxy_ticker = yf.Ticker('DX-Y.NYB')
        dxy_hist = dxy_ticker.history(period='1d')
        dxy_val = dxy_hist['Close'].iloc[-1] if not dxy_hist.empty else 100.0

        # TNX: US 10-Year Treasury Yield (Critical for GOLD & Growth)
        tnx_ticker = yf.Ticker('^TNX')
        tnx_hist = tnx_ticker.history(period='1d')
        tnx_val = tnx_hist['Close'].iloc[-1] if not tnx_hist.empty else 4.0

        # Calculate Danger Level (0-100)
        danger_level = 0
        if vix_val > 35 or tnx_val > 5.0:
            danger_level = 90
        elif vix_val > 25 or tnx_val > 4.5:
            danger_level = 60
        elif vix_val > 20:
            danger_level = 30
        else:
            danger_level = 10

        return {
            "vix": float(vix_val),
            "dxy": float(dxy_val),
            "yield_10y": float(tnx_val),
            "danger_level": danger_level,
            "regime": "EXTREME_VOLATILITY" if vix_val > 30 else "TENSE" if vix_val > 20 else "STABLE",
            "risk_multiplier": 0.5 if vix_val > 30 or tnx_val > 5.0 else 0.8 if vix_val > 20 else 1.0
        }
    except Exception as e:
        logger.error(f"MacroTools: Failed to fetch risk data: {e}")
        return {
            "vix": 15.0,
            "dxy": 100.0,
            "danger_level": 10,
            "regime": "UNKNOWN",
            "risk_multiplier": 1.0
        }

if __name__ == "__main__":
    print(get_macro_risk_data())
