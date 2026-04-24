import logging
import time
from datetime import datetime, time as dt_time
from typing import Dict, Any, Optional
try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

logger = logging.getLogger(__name__)

class InstitutionalGuard:
    """
    Final security layer before MetaTrader 5 execution.
    Implements Spread, Exposure, and Time-based protection.
    """

    MAX_SPREAD_PIPS = {
        "GOLD": 50,    # Max 50 points spread for GOLD
        "BTCUSD": 1000, # Max 1000 points for BTC
        "EURUSD": 20,   # Max 20 points for Major Forex
        "GBPUSD": 25,
    }

    MAX_CONCURRENT_POSITIONS = 3 # Max 3 positions per symbol

    @staticmethod
    def check_all_guards(symbol: str, side: str) -> bool:
        """Runs all safety checks. Returns True if SAFE to trade."""
        if not InstitutionalGuard.check_time_guard():
            return False
        if not InstitutionalGuard.check_spread_guard(symbol):
            return False
        if not InstitutionalGuard.check_exposure_guard(symbol):
            return False

        logger.info(f"🛡️ Guards: All checks PASSED for {symbol} {side}")
        return True

    @staticmethod
    def check_time_guard() -> bool:
        """Blocks trading during high-risk periods (Rollover, Weekends)."""
        now = datetime.utcnow()

        # 1. Weekend Check (Friday 22:00 UTC to Sunday 22:00 UTC)
        if now.weekday() == 4 and now.hour >= 22:
            logger.warning("🛡️ TimeGuard Block: Market Closing (Friday)")
            return False
        if now.weekday() == 5:
            logger.warning("🛡️ TimeGuard Block: Weekend (Saturday)")
            return False
        if now.weekday() == 6 and now.hour < 22:
            logger.warning("🛡️ TimeGuard Block: Market Opening (Sunday)")
            return False

        # 2. Daily Rollover Check (21:55 - 22:10 UTC) - High Volatility/Spread
        rollover_start = dt_time(21, 55)
        rollover_end = dt_time(22, 10)
        current_time = now.time()

        if rollover_start <= current_time <= rollover_end:
            logger.warning(f"🛡️ TimeGuard Block: Daily Rollover period ({current_time})")
            return False

        return True

    @staticmethod
    def check_spread_guard(symbol: str) -> bool:
        """Checks if current broker spread is within acceptable limits."""
        if mt5 is None:
            return True # If MT5 not available, skip check

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            logger.warning(f"🛡️ SpreadGuard: Symbol {symbol} not found")
            return False

        current_spread = symbol_info.spread
        max_allowed = InstitutionalGuard.MAX_SPREAD_PIPS.get(symbol, 50) # Default 50

        if current_spread > max_allowed:
            logger.warning(f"🛡️ SpreadGuard Block: {symbol} spread too high ({current_spread} > {max_allowed})")
            return False

        return True

    @staticmethod
    def check_exposure_guard(symbol: str) -> bool:
        """Ensures we are not over-exposed to a single asset."""
        if mt5 is None:
            return True

        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            return True # No positions, safe

        if len(positions) >= InstitutionalGuard.MAX_CONCURRENT_POSITIONS:
            logger.warning(f"🛡️ ExposureGuard Block: Too many positions for {symbol} ({len(positions)})")
            return False

        return True
