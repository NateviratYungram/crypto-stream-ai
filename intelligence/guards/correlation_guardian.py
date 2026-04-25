import logging
from typing import Any, Dict, List

from intelligence.mt5_connector import _MT5_AVAILABLE

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

# MT5-tradeable peers to cross-check for directional confirmation.
# STOCK assets are excluded — they are not MT5-tradeable in this system.
_DIRECTIONAL_PEERS: Dict[str, List[str]] = {
    # Crypto: confirm broader crypto sentiment
    "BTCUSD": ["ETHUSD", "SOLUSD"],
    "ETHUSD": ["BTCUSD", "SOLUSD"],
    "SOLUSD": ["BTCUSD", "ETHUSD"],
    "XRPUSD": ["BTCUSD"],
    "BTC":    ["ETH", "SOL"],
    "ETH":    ["BTC", "SOL"],
    "SOL":    ["BTC", "ETH"],
    # Forex majors: confirm USD directional bias
    "EURUSD": ["GBPUSD", "AUDUSD"],
    "GBPUSD": ["EURUSD", "AUDUSD"],
    "AUDUSD": ["EURUSD", "NZDUSD"],
    "NZDUSD": ["AUDUSD"],
    "USDJPY": ["USDCHF"],
    "USDCHF": ["USDJPY"],
    "USDCAD": ["USDJPY"],
    # Forex crosses
    "EURJPY": ["GBPJPY", "AUDJPY"],
    "GBPJPY": ["EURJPY", "AUDJPY"],
    "AUDJPY": ["EURJPY"],
    # Metals: confirm safe-haven flow
    "GOLD":   ["SILVER"],
    "SILVER": ["GOLD"],
    "XAUUSD": ["SILVER"],
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


def check_directional_correlation(
    symbol: str,
    side: str,
    asset_class: str = "CRYPTO",
) -> Dict[str, Any]:
    """
    For MT5-tradeable assets (CRYPTO, MACRO), check whether correlated peer
    assets confirm the proposed trade direction via a quick price-vs-EMA50 check.

    Stocks are excluded — they are not MT5-tradeable in this system.

    Returns:
        confirmed  : True if ≥50% of peers confirm (or no peers available)
        score      : float 0-1, fraction of confirming peers
        conflicts  : list of peer symbols that contradict the direction
        checked    : number of peers successfully fetched
    """
    if asset_class == "STOCK":
        return {"confirmed": True, "score": 1.0, "conflicts": [], "checked": 0}

    sym_key = symbol.upper().replace("-", "").replace("=X", "").replace("USDT", "USD")
    peers: List[str] = _DIRECTIONAL_PEERS.get(sym_key, [])
    if not peers:
        return {"confirmed": True, "score": 1.0, "conflicts": [], "checked": 0}

    try:
        from intelligence.technical_engine import compute_indicators, get_kline_data
    except Exception:
        return {"confirmed": True, "score": 1.0, "conflicts": [], "checked": 0}

    confirming = 0
    conflicts: List[str] = []

    for peer in peers:
        try:
            peer_ac = "CRYPTO" if any(
                c in peer for c in ["BTC", "ETH", "SOL", "XRP", "BNB"]
            ) else asset_class
            df_peer = get_kline_data(peer, "1h", limit=60, asset_class=peer_ac)
            if df_peer is None or len(df_peer) < 50:
                continue
            df_peer = compute_indicators(df_peer)
            price  = float(df_peer["Close"].iloc[-1])
            ema50  = float(df_peer["ema_50"].iloc[-1])
            peer_bullish = price > ema50
            if (side == "LONG" and peer_bullish) or (side == "SHORT" and not peer_bullish):
                confirming += 1
            else:
                conflicts.append(peer)
        except Exception as exc:
            logger.debug(f"CorrelationGuardian: peer {peer} fetch failed: {exc}")

    total = confirming + len(conflicts)
    if total == 0:
        return {"confirmed": True, "score": 1.0, "conflicts": [], "checked": 0}

    score = confirming / total
    logger.info(
        f"CorrelationGuardian: {symbol} {side} — "
        f"{confirming}/{total} peers confirm (score={score:.2f}, conflicts={conflicts})"
    )
    return {
        "confirmed": score >= 0.5,
        "score":     round(score, 2),
        "conflicts": conflicts,
        "checked":   total,
    }
