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

def get_mt5_positions() -> List[Dict[str, Any]]:
    """Fetch all open positions from MT5."""
    if not _MT5_AVAILABLE:
        return []
    if not initialize_mt5():
        return []

    positions = mt5.positions_get()
    if positions is None:
        return []

    return [p._asdict() for p in positions]

def get_mt5_quote(symbol: str) -> Dict[str, Any]:
    """Fetch current MT5 bid/ask and basic symbol trading metadata."""
    if not _MT5_AVAILABLE:
        return {"error": "MetaTrader5 not installed. Install it to enable live trading."}
    if not initialize_mt5():
        return {"error": "Failed to connect to MT5"}

    if not mt5.symbol_select(symbol, True):
        return {"error": f"Failed to select symbol {symbol}"}

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return {"error": f"Quote unavailable for {symbol}", "last_error": mt5.last_error()}

    return {
        "symbol": symbol,
        "bid": tick.bid,
        "ask": tick.ask,
        "last": tick.last,
        "spread": (tick.ask - tick.bid) if tick.ask and tick.bid else 0.0,
        "time": tick.time,
        "digits": info.digits,
        "point": info.point,
        "volume_min": info.volume_min,
        "volume_max": info.volume_max,
        "volume_step": info.volume_step,
        "trade_mode": info.trade_mode,
        "trade_contract_size": info.trade_contract_size,
    }

def mt5_execute_trade(symbol: str, action: str, volume: float, price: Optional[float] = None,
                      sl: Optional[float] = None, tp: Optional[float] = None,
                      comment: str = "CryptoStream AI Trade",
                      order_kind: str = "MARKET",
                      filling_policy: str = "IOC",
                      deviation: int = 20,
                      expiration: Optional[int] = None) -> Dict[str, Any]:
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

    action_upper = action.upper()
    order_kind_upper = order_kind.upper()
    filling_upper = filling_policy.upper()

    order_type_map = {
        "BUY": mt5.ORDER_TYPE_BUY,
        "SELL": mt5.ORDER_TYPE_SELL,
        "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
        "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
        "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
        "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
        "BUY_STOP_LIMIT": mt5.ORDER_TYPE_BUY_STOP_LIMIT,
        "SELL_STOP_LIMIT": mt5.ORDER_TYPE_SELL_STOP_LIMIT,
    }
    filling_map = {
        "FOK": mt5.ORDER_FILLING_FOK,
        "IOC": mt5.ORDER_FILLING_IOC,
        "RETURN": mt5.ORDER_FILLING_RETURN,
    }

    if order_kind_upper == "MARKET":
        order_type = mt5.ORDER_TYPE_BUY if action_upper == "BUY" else mt5.ORDER_TYPE_SELL
        trade_action = mt5.TRADE_ACTION_DEAL
    else:
        order_type = order_type_map.get(action_upper)
        if order_type is None:
            return {"error": f"Unsupported pending order type: {action}"}
        if price is None or price <= 0:
            return {"error": "Pending orders require a valid entry price"}
        trade_action = mt5.TRADE_ACTION_PENDING

    # Get current price if not provided
    if order_kind_upper == "MARKET" and price is None:
        tick = mt5.symbol_info_tick(symbol)
        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

    request = {
        "action": trade_action,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl if sl else 0.0,
        "tp": tp if tp else 0.0,
        "deviation": int(deviation),
        "magic": 123456,
        "comment": comment[:31] if comment else "",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_map.get(filling_upper, mt5.ORDER_FILLING_IOC),
    }
    if expiration:
        request["type_time"] = mt5.ORDER_TIME_SPECIFIED
        request["expiration"] = int(expiration)

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
        "comment": result.comment,
        "request": request,
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

def mt5_get_rates(symbol: str, timeframe: str = "15m", count: int = 100) -> Optional[Any]:
    """
    Fetch OHLCV data directly from MetaTrader 5.
    Returns bars as a pandas-ready format or None if failed.
    """
    if not _MT5_AVAILABLE:
        return None
    if not initialize_mt5():
        return None

    # Map timeframes
    tf_map = {
        "1m":  mt5.TIMEFRAME_M1,
        "5m":  mt5.TIMEFRAME_M5,
        "15m": mt5.TIMEFRAME_M15,
        "30m": mt5.TIMEFRAME_M30,
        "1h":  mt5.TIMEFRAME_H1,
        "4h":  mt5.TIMEFRAME_H4,
        "1d":  mt5.TIMEFRAME_D1,
    }
    mt5_tf = tf_map.get(timeframe, mt5.TIMEFRAME_M15)

    # Normalize symbol for broker (e.g. XM)
    candidates = normalize_broker_symbol(symbol)
    resolved_sym = None
    for sym in candidates:
        if mt5.symbol_select(sym, True):
            resolved_sym = sym
            break

    if not resolved_sym:
        logger.warning(f"MT5: Symbol {symbol} not found in Market Watch (checked: {candidates})")
        return None

    # Fetch rates (from current position back 'count' bars)
    rates = mt5.copy_rates_from_pos(resolved_sym, mt5_tf, 0, count)
    if rates is None or len(rates) == 0:
        logger.error(f"MT5: Failed to fetch rates for {resolved_sym}, error: {mt5.last_error()}")
        return None

    import pandas as pd
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')

    # Standardize to our engine's format
    df = df.rename(columns={
        'time': 'Datetime',
        'open': 'Open',
        'high': 'High',
        'low': 'Low',
        'close': 'Close',
        'tick_volume': 'Volume'
    })

    logger.info(f"MT5: Successfully fetched {len(df)} bars for {resolved_sym} ({timeframe})")
    return df[['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']]

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
