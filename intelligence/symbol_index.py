import logging
from typing import List, Dict, Any
import re

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    _MT5_AVAILABLE = False

logger = logging.getLogger(__name__)

def search_market_symbols(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Institutional fuzzy search for instruments.
    Matches symbols by ticker name or description.
    """
    logger.info(f"SymbolIndex: Searching for '{query}'...")

    try:
        if not _MT5_AVAILABLE:
            return []
        from intelligence.mt5_connector import initialize_mt5
        if not initialize_mt5():
            return []

        # 1. Get all available symbols from MT5
        all_symbols = mt5.symbols_get()
        if not all_symbols:
            return []

        query_clean = query.strip().upper()
        results = []

        # 2. Local fuzzy matching (Case-insensitive Regex)
        pattern = re.compile(re.escape(query_clean), re.IGNORECASE)

        for s in all_symbols:
            # Match against symbol name (e.g., BTCUSD) or description (e.g., Bitcoin)
            if pattern.search(s.name) or pattern.search(s.description):
                results.append({
                    "symbol": s.name,
                    "description": s.description,
                    "digits": s.digits,
                    "spread": s.spread,
                    "trade_mode": s.trade_mode,
                    "base": s.path.split("\\")[0] if "\\" in s.path else "Unknown"
                })

            if len(results) >= limit:
                break

        # 3. Sort by exact name match first (relevance)
        results.sort(key=lambda x: 0 if x["symbol"].upper() == query_clean else 1)

        logger.info(f"SymbolIndex: Found {len(results)} matches for '{query}'.")
        return results
    except Exception as e:
        logger.error(f"Error in search_market_symbols: {e}")
        return []

def resolve_symbol(common_name: str) -> str:
    """Helper to map a common name to the most relevant MT5 ticker."""
    matches = search_market_symbols(common_name, limit=1)
    if matches:
        return matches[0]["symbol"]
    return common_name.upper()
