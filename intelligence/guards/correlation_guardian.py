import logging
from typing import Dict, Any, List
from intelligence.mt5_connector import get_mt5_account_info, _MT5_AVAILABLE

logger = logging.getLogger(__name__)

# Exposure threshold per "Correlation Group"
MAX_POSITIONS_PER_GROUP = 2

# Definition of Correlation Groups
CORRELATION_GROUPS = {
    "USD_PAIRS": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "CRYPTO": ["BTCUSD", "ETHUSD", "SOLUSD", "BTC", "ETH", "SOL"],
    "INDICES": ["US100Cash", "US500Cash", "US30Cash", "GER40Cash", "NASDAQ", "SP500", "US100", "US500"],
    "METALS": ["GOLD", "XAUUSD", "SILVER", "XAGUSD"]
}

def check_correlation_safety(new_symbol: str) -> Dict[str, Any]:
    """
    Analyzes current MT5 positions and determines if adding 'new_symbol' 
    would violate correlation/exposure limits.
    """
    if not _MT5_AVAILABLE:
        return {"passed": True} # Cannot check without MT5

    try:
        try:
            import MetaTrader5 as mt5
        except ImportError:
            return {"passed": True}

        # 1. Fetch current positions
        positions = mt5.positions_get()
        if positions is None or len(positions) == 0:
            return {"passed": True}

        # 2. Determine the group for the new symbol
        new_group = None
        for group_name, symbols in CORRELATION_GROUPS.items():
            if any(s in new_symbol.upper() for s in symbols):
                new_group = group_name
                break
        
        if not new_group:
            return {"passed": True} # Unknown group, let it pass

        # 3. Count existing positions in that group
        count = 0
        existing_assets = []
        for pos in positions:
            if any(s in pos.symbol.upper() for s in CORRELATION_GROUPS[new_group]):
                count += 1
                existing_assets.append(pos.symbol)

        # 4. Enforce limit
        if count >= MAX_POSITIONS_PER_GROUP:
            return {
                "passed": False,
                "reason": f"Correlation Overload: Already have {count} positions in {new_group} ({', '.join(existing_assets)}).",
                "group": new_group,
                "current_count": count
            }

        return {"passed": True, "current_group_count": count}

    except Exception as e:
        logger.error(f"CorrelationGuardian: Check failed: {e}")
        return {"passed": True} # Fail safe (allow) but log error
