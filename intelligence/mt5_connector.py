import logging
import os
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Optional MT5 import — graceful fallback if not installed
try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    _MT5_AVAILABLE = False
    logger.warning("MetaTrader5 not installed — MT5 execution disabled. Analysis tools will still work.")

from intelligence.event_logger import log_trade_attempt, log_guard_failure

def _get_guard_pipeline():
    from intelligence.guards import GuardPipeline, MaxPositionSizeGuard, CooldownGuard
    return GuardPipeline([
        MaxPositionSizeGuard(max_equity_pct=2.0),
        CooldownGuard(cooldown_seconds=300)
    ])

def initialize_mt5() -> bool:
    """Initialize connection to MetaTrader 5."""
    if not _MT5_AVAILABLE:
        logger.warning("MT5: MetaTrader5 package not installed.")
        return False
    if not mt5.initialize():
        logger.error(f"MT5: Initialize failed, error code: {mt5.last_error()}")
        return False
    logger.info("MT5: Connection initialized successfully.")
    return True

def get_mt5_account_info() -> Dict[str, Any]:
    """Fetch MT5 account details."""
    if not _MT5_AVAILABLE:
        return {"error": "MetaTrader5 not installed. Install it to enable live trading."}
    if not initialize_mt5():
        return {"error": "Failed to connect to MT5"}
    
    account_info = mt5.account_info()
    if account_info is None:
        return {"error": f"Failed to get account info, error code: {mt5.last_error()}"}
    
    return account_info._asdict()

def mt5_execute_trade(symbol: str, action: str, volume: float, price: Optional[float] = None,
                      sl: Optional[float] = None, tp: Optional[float] = None,
                      comment: str = "CryptoStream AI Trade") -> Dict[str, Any]:
    """
    Execute a trade on MT5.
    action: 'BUY', 'SELL'
    """
    if not _MT5_AVAILABLE:
        return {"error": "MetaTrader5 not installed. Install it to enable live trading."}
    if not initialize_mt5():
        return {"error": "Failed to connect to MT5"}

    # ── Execution Guards ──────────────────────────────────────────────────────
    try:
        account_info = get_mt5_account_info()
        pipeline = _get_guard_pipeline()
        order_params = {
            "symbol": symbol,
            "action": action.upper(),
            "volume": volume,
            "price": price
        }
        passed, guard_results = pipeline.run(order_params, account_info)
        if not passed:
            log_guard_failure(guard_name="GuardPipeline", message=str(guard_results))
            logger.warning(f"MT5: Trade blocked by guards: {guard_results}")
            return {
                "status": "GUARD_BLOCKED",
                "message": "Execution-time safety guards triggered.",
                "results": guard_results
            }
        
        # Log the attempt to the institutional audit audit trail
        log_trade_attempt(symbol=symbol, action=action, volume=volume, reason=f"Manual execution via agent. Guards: OK")
    except Exception as guard_err:
        logger.error(f"MT5: Guard check failed, proceeding with caution: {guard_err}")

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return {"error": f"Symbol {symbol} not found"}
    
    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            return {"error": f"Failed to select symbol {symbol}"}

    # Define order type
    order_type = mt5.ORDER_TYPE_BUY if action.upper() == "BUY" else mt5.ORDER_TYPE_SELL
    
    # Get current price if not provided
    if price is None:
        tick = mt5.symbol_info_tick(symbol)
        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl if sl else 0.0,
        "tp": tp if tp else 0.0,
        "magic": 123456,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    # Send order
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"MT5 Order failed: {result.comment} (code: {result.retcode})")
        return {
            "status": "FAILED",
            "retcode": result.retcode,
            "comment": result.comment,
            "error_details": str(result)
        }

    return {
        "status": "SUCCESS",
        "order_id": result.order,
        "deal_id": result.deal,
        "price": result.price,
        "volume": result.volume,
        "comment": result.comment
    }

def mt5_close_position(ticket: int) -> Dict[str, Any]:
    """Close an open position by ticket ID."""
    if not _MT5_AVAILABLE:
        return {"error": "MetaTrader5 not installed. Install it to enable live trading."}
    if not initialize_mt5():
        return {"error": "Failed to connect to MT5"}

    position = mt5.positions_get(ticket=ticket)
    if not position:
        return {"error": f"Position {ticket} not found"}

    pos = position[0]
    symbol = pos.symbol
    order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(symbol)
    price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": pos.volume,
        "type": order_type,
        "position": ticket,
        "price": price,
        "magic": 123456,
        "comment": "Close via CryptoStream AI",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"status": "FAILED", "comment": result.comment}

    return {"status": "SUCCESS", "deal": result.deal}

def mt5_modify_position(ticket: int, sl: float, tp: float = 0.0) -> Dict[str, Any]:
    """
    Modify an open position's Stop Loss and Take Profit.
    Uses TRADE_ACTION_SLTP.
    """
    if not _MT5_AVAILABLE:
        return {"error": "MetaTrader5 not installed."}
    if not initialize_mt5():
        return {"error": "Failed to connect to MT5"}

    position = mt5.positions_get(ticket=ticket)
    if not position:
        logger.error(f"MT5: Position {ticket} not found for modification")
        return {"error": f"Position {ticket} not found"}

    pos = position[0]
    symbol = pos.symbol

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": symbol,
        "position": ticket,
        "sl": float(sl),
        "tp": float(tp) if tp else float(pos.tp),
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"MT5: Position modification failed: {result.comment} (code: {result.retcode})")
        return {
            "status": "FAILED",
            "retcode": result.retcode,
            "comment": result.comment
        }

    logger.info(f"MT5: Position {ticket} modified successfully (SL={sl}, TP={tp})")
    return {
        "status": "SUCCESS",
        "ticket": ticket,
        "sl": result.request.sl,
        "tp": result.request.tp
    }

def normalize_broker_symbol(symbol: str) -> List[str]:
    """
    Normalizes symbols based on detected broker (e.g., XM Global).
    Returns a list of candidate symbols to search in MT5.
    """
    symbol_upper = symbol.strip().upper()
    candidates = [symbol_upper]

    try:
        if _MT5_AVAILABLE:
            acc = get_mt5_account_info()
            company = str(acc.get("company", "")).upper()
            is_xm = "XM GLOBAL" in company or "XM.COM" in company
            
            if is_xm:
                logger.info(f"MT5: XM Broker detected ({company}). Applying symbol resolution rules.")
                # XM Index / Commodity / Forex Mapping
                xm_map = {
                    # Indices
                    "NASDAQ":   ["US100Cash", "US100"],
                    "NDX":      ["US100Cash", "US100"],
                    "NAS100":   ["US100Cash", "US100"],
                    "SP500":    ["US500Cash", "US500"],
                    "SPX":      ["US500Cash", "US500"],
                    "US500":    ["US500Cash", "US500"],
                    "DOW":      ["US30Cash",  "US30"],
                    "DJI":      ["US30Cash",  "US30"],
                    "US30":     ["US30Cash",  "US30"],
                    "GER40":    ["GER40Cash", "DE40"],
                    "DAX":      ["GER40Cash", "DE40"],
                    "UK100":    ["UK100Cash", "UK100"],
                    "JPN225":   ["JP225Cash", "JPN225"],
                    # Commodities
                    "GOLD":     ["GOLD",   "GOLDm",  "XAUUSD"],
                    "XAU":      ["GOLD",   "GOLDm",  "XAUUSD"],
                    "XAUUSD":   ["GOLD",   "GOLDm"],
                    "SILVER":   ["SILVER", "XAGUSDm","XAGUSD"],
                    "XAG":      ["SILVER", "XAGUSDm","XAGUSD"],
                    "XAGUSD":   ["SILVER", "XAGUSDm"],
                    "OIL":      ["USOIL",  "WTI",    "XTIUSD", "OILCash"],
                    "USOIL":    ["USOIL",  "WTI",    "OILCash"],
                    "WTI":      ["USOIL",  "WTI"],
                    "BRENT":    ["UKOIL",  "BRENTCash"],
                    # Crypto (XM uses XXXUSD notation)
                    "BTC":      ["BTCUSD"],
                    "ETH":      ["ETHUSD"],
                    "SOL":      ["SOLUSD"],
                    "BNB":      ["BNBUSD"],
                    "XRP":      ["XRPUSD"],
                    "DOGE":     ["DOGEUSD"],
                    "AVAX":     ["AVAXUSD"],
                    "LINK":     ["LINKUSD"],
                    "ADA":      ["ADAUSD"],
                    "DOT":      ["DOTUSD"],
                    "MATIC":    ["MATICUSD","POLUSD"],
                }
                if symbol_upper in xm_map:
                    candidates = xm_map[symbol_upper] + candidates

                # XM Stocks use # suffix (e.g. NVDA#, TSLA#)
                known_stocks = {
                    "NVDA","TSLA","AAPL","AMZN","MSFT","META","AMD",
                    "GOOGL","GOOG","NFLX","JPM","BAC","UBER","SPY","QQQ",
                }
                if symbol_upper in known_stocks:
                    candidates = [f"{symbol_upper}#"] + candidates

    except Exception as e:
        logger.warning(f"MT5: Broker symbol normalization failed: {e}")
    
    # Standard fallbacks
    standard_fallbacks = [f"{symbol_upper}USD", f"{symbol_upper}USDT", f"{symbol_upper}."]
    for f in standard_fallbacks:
        if f not in candidates:
            candidates.append(f)
            
    return candidates
