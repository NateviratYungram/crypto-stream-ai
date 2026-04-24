import logging
import requests
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class WhalePulseEngine:
    """
    Monitors institutional 'Whale' activity using Level 2 Order Books
    and High-Speed Volume Anomaly Detection.
    """

    def __init__(self):
        self.binance_base_url = "https://api.binance.com/api/v3"

    def get_whale_walls(self, symbol: str) -> Dict[str, Any]:
        """
        Scans the Binance Depth (Order Book) for anomalously large limit orders.
        Whale Wall = Orders >= 5x the average order size in the top 100 levels.
        """
        try:
            # Standardize symbol for Binance
            clean_sym = symbol.upper().replace("USDT", "").replace("-USD", "") + "USDT"

            # Map common special symbols (e.g. GOLD) to something we can approximate or skip
            # For now, if it's not a common crypto, we skip the L2 depth check
            if any(x in clean_sym for x in ["GC=F", "GOLD", "XAU", "NASDAQ"]):
                return {"walls": [], "bias": "NEUTRAL", "message": "Deep L2 Depth restricted for Macro assets"}

            url = f"{self.binance_base_url}/depth"
            params = {"symbol": clean_sym, "limit": 100}
            r = requests.get(url, params=params, timeout=5)

            if r.status_code != 200:
                return {"walls": [], "bias": "NEUTRAL", "error": "Order Book unavailable"}

            data = r.json()
            bids = data.get("bids", [])
            asks = data.get("asks", [])

            # Filter for Whale Walls
            def filter_walls(levels, side):
                if not levels:
                    return []
                volumes = [float(level[1]) for level in levels]
                avg_vol = sum(volumes) / len(volumes)

                whale_levels = []
                for price, vol in levels:
                    v = float(vol)
                    if v > avg_vol * 4.5:
                        whale_levels.append({
                            "type": f"WHALE_{side.upper()}_WALL",
                            "price": round(float(price), 4),
                            "volume": round(v, 4),
                            "strength": round(v / avg_vol, 1)
                        })
                return whale_levels

            buy_walls = filter_walls(bids, "buy")
            sell_walls = filter_walls(asks, "sell")

            bias = "NEUTRAL"
            if len(buy_walls) > len(sell_walls):
                bias = "ACCUMULATION"
            elif len(sell_walls) > len(buy_walls):
                bias = "DISTRIBUTION"

            return {
                "buy_walls": buy_walls[:3],
                "sell_walls": sell_walls[:3],
                "bias": bias,
                "message": f"Detected {len(buy_walls)} support walls and {len(sell_walls)} resistance walls."
            }
        except Exception as e:
            logger.error(f"WhaleEngine: Wall detection failed: {e}")
            return {"walls": [], "bias": "NEUTRAL"}

    def detect_volume_injections(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Identifies 'Institutional Injections' in price history.
        Injection = Volume > 3x the 20-period Moving Average.
        """
        if df is None or df.empty or "Volume" not in df.columns:
            return []

        try:
            df = df.copy()
            df["vol_sma"] = df["Volume"].rolling(window=20).mean()

            # Look at the last 5 candles for injections
            recent = df.tail(5)
            injections = []

            for idx, row in recent.iterrows():
                if row["vol_sma"] > 0 and row["Volume"] > row["vol_sma"] * 2.8:
                    side = "BULLISH_INJECTION" if row["Close"] > row["Open"] else "BEARISH_INJECTION"
                    injections.append({
                        "type": side,
                        "time": str(row["Datetime"]),
                        "multiplier": round(row["Volume"] / row["vol_sma"], 1),
                        "price": round(row["Close"], 4)
                    })

            return injections
        except Exception as e:
            logger.error(f"WhaleEngine: Injection detection failed: {e}")
            return []

    def get_institutional_bias(self, symbol: str, df: pd.DataFrame) -> Dict[str, Any]:
        """Combines Order Book and Volume analysis into a single bias report."""
        walls = self.get_whale_walls(symbol)
        injections = self.detect_volume_injections(df)

        # Aggregate bias
        final_bias = walls.get("bias", "NEUTRAL")
        if any(i["type"] == "BULLISH_INJECTION" for i in injections):
            final_bias = "ACCUMULATION" if final_bias != "DISTRIBUTION" else "FIGHTING"
        elif any(i["type"] == "BEARISH_INJECTION" for i in injections):
            final_bias = "DISTRIBUTION" if final_bias != "ACCUMULATION" else "FIGHTING"

        return {
            "bias": final_bias,
            "walls": {
                "buy": walls.get("buy_walls", []),
                "sell": walls.get("sell_walls", [])
            },
            "recent_injections": injections,
            "institutional_confidence": "HIGH" if len(injections) > 0 or len(walls.get("buy_walls", [])) > 0 else "LOW"
        }

# Global Instance
whale_pulse = WhalePulseEngine()
