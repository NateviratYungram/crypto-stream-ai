import requests
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class OnChainTools:
    """
    Fetches on-chain and derivative flow data to gauge retail sentiment.
    Used for 'Contrarian Trading' (Trade against the herd).
    """
    def __init__(self):
        self.binance_fapi = "https://fapi.binance.com/fapi/v1"
        self.binance_data_api = "https://fapi.binance.com/futures/data"

    def get_fomo_heatmap(self, symbol: str) -> Dict[str, Any]:
        """
        Fetches the Global Long/Short Account Ratio from Binance Futures.
        If Retail is heavily Long (>65%), the institutional bias is SHORT.
        Warning: This only works for Crypto (e.g. BTCUSD -> BTCUSDT).
        """
        if symbol in ["GOLD", "XAUUSD", "US30", "SPX", "NAS100", "USOIL"]:
            return {"status": "UNAVAILABLE", "reason": "Not a crypto asset"}

        # Normalize symbol for Binance (e.g., BTCUSD -> BTCUSDT)
        if hasattr(symbol, "upper"):
            sym = symbol.upper().replace("USD", "USDT")
        else:
            sym = "BTCUSDT"

        try:
            # 5m period gives us the immediate FOMO trend
            url = f"{self.binance_data_api}/globalLongShortAccountRatio?symbol={sym}&period=5m&limit=1"
            r = requests.get(url, timeout=5)

            if r.status_code == 200:
                data = r.json()
                if len(data) > 0:
                    latest = data[0]
                    long_ratio = float(latest.get("longAccount", 0.5)) * 100
                    short_ratio = float(latest.get("shortAccount", 0.5)) * 100

                    # Sentiment Analysis
                    fomo_status = "NEUTRAL"
                    inst_bias = "NEUTRAL"
                    if long_ratio > 65:
                        fomo_status = "EXTREME_LONG_FOMO"
                        inst_bias = "SHORT" # Retail is long, institutions will hunt them
                    elif short_ratio > 65:
                        fomo_status = "EXTREME_SHORT_FOMO"
                        inst_bias = "LONG"

                    return {
                        "status": "SUCCESS",
                        "long_percent": round(long_ratio, 2),
                        "short_percent": round(short_ratio, 2),
                        "retail_sentiment": fomo_status,
                        "institutional_bias": inst_bias
                    }
            return {"status": "FAILED", "reason": f"API returned {r.status_code}"}
        except Exception as e:
            logger.error(f"OnChainTools: Failed to fetch FOMO heatmap: {e}")
            return {"status": "ERROR", "reason": str(e)}

onchain_engine = OnChainTools()

if __name__ == "__main__":
    print(onchain_engine.get_fomo_heatmap("BTC"))
