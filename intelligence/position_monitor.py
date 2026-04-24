"""
CryptoStream AI — Position Monitor
Manages open MT5 positions with trailing SL, break-even, and max hold time.

Ported from QuantAgent position_monitor.py — adapted for CryptoStream:
  - Removed symbol_specs pip conversion (uses raw price differences)
  - Uses MT5 symbol_info.point for min price increment
  - Configurable magic number per symbol
  - Integrates with circuit_breaker.record_trade_close() on forced exits
  - Works for crypto (24/7) and macro (XAUUSD, NAS100, etc.)

Usage:
    from intelligence.position_monitor import PositionMonitor

    pm = PositionMonitor(config={
        "mt5_magic_number": 789456,
        "max_hold_hours": 8,
        "trail_ratio": 0.5,
    })

    # Call from a scheduler every 1–5 minutes
    result = pm.check_positions()
    for action in result["actions"]:
        print(action)
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PM_CONFIG = {
    "mt5_magic_number":  789456,    # Must match magic used when opening trades
    "max_hold_hours":    8,         # Close position after this many hours (swap protection)
    "break_even_rr":     1.0,       # Move SL to BE when profit >= 1×SL distance
    "trail_trigger_rr":  1.5,       # Activate trailing SL when profit >= 1.5×SL distance
    "trail_ratio":       0.5,       # Trail by 50% of initial SL distance
    "be_buffer_pips":    2,         # Pips above entry for BE (covers spread)
    "filter_symbol":     None,      # If set, only monitor this symbol (e.g. "BTCUSD")
}


class PositionMonitor:
    """
    Monitors and manages open MT5 positions placed by CryptoStream AI.

    Rules applied per position (in order):
      1. Max hold time → force-close (avoids crypto/CFD swap accumulation)
      2. Break-even    → move SL to entry + buffer (locks capital, risk-free)
      3. Trailing SL   → ratchet SL behind price as it moves in favour
    """

    def __init__(self, config: dict = None):
        self.config = {**DEFAULT_PM_CONFIG, **(config or {})}

    # ── Public API ─────────────────────────────────────────────────────────────

    def check_positions(self) -> dict:
        """
        Scan all open bot positions and apply management rules.

        Returns:
            {
              "status":  str,
              "actions": list[dict]   # one dict per position evaluated
            }
        """
        try:
            import MetaTrader5 as mt5
        except ImportError:
            return {"status": "MT5 not installed", "actions": []}

        try:
            if not mt5.initialize():
                return {"status": "MT5 not available", "actions": []}

            magic          = int(self.config["mt5_magic_number"])
            filter_symbol  = self.config.get("filter_symbol")
            actions        = []

            # Fetch positions — optionally filtered by symbol
            if filter_symbol:
                positions = mt5.positions_get(symbol=filter_symbol) or []
            else:
                positions = mt5.positions_get() or []

            if not positions:
                mt5.shutdown()
                return {"status": "No open positions", "actions": []}

            for pos in positions:
                if pos.magic != magic:
                    continue  # skip positions not placed by this bot
                action = self._evaluate_position(pos, mt5)
                if action:
                    actions.append(action)
                    logger.info(
                        f"PositionMonitor: #{pos.ticket} {pos.symbol} "
                        f"→ {action['action']} ({action.get('reason', '')})"
                    )

            mt5.shutdown()
            return {"status": "OK", "actions": actions}

        except Exception as e:
            logger.exception("PositionMonitor.check_positions error")
            return {"status": f"Error: {e}", "actions": []}

    # ── Internal evaluation ────────────────────────────────────────────────────

    def _evaluate_position(self, pos, mt5) -> Optional[dict]:
        """Evaluate a single position and decide on action."""
        symbol_info = mt5.symbol_info(pos.symbol)
        if not symbol_info:
            return None

        tick = mt5.symbol_info_tick(pos.symbol)
        if not tick:
            return None

        # Current price (bid for SELL to close, ask for BUY to close)
        is_buy        = pos.type == 0
        current_price = tick.bid if is_buy else tick.ask

        # Profit distance in price terms
        if is_buy:
            profit_price = current_price - pos.price_open
        else:
            profit_price = pos.price_open - current_price

        # Initial SL distance (fallback 10 × point)
        point = symbol_info.point
        if pos.sl > 0:
            sl_distance = abs(pos.price_open - pos.sl)
        else:
            sl_distance = 10 * point

        # ── Rule 1: Max Hold Time ──────────────────────────────────────────────
        max_hours  = float(self.config["max_hold_hours"])
        open_time  = datetime.fromtimestamp(pos.time)
        hold_hours = (datetime.now() - open_time).total_seconds() / 3600

        if hold_hours >= max_hours:
            closed = self._close_position(pos, mt5, "Max hold time")
            if closed:
                self._record_close(pos)
            return {
                "ticket":     pos.ticket,
                "symbol":     pos.symbol,
                "action":     "CLOSED",
                "reason":     f"Held {hold_hours:.1f}h (max {max_hours}h)",
                "profit_usd": round(pos.profit, 2),
                "closed":     closed,
            }

        # ── Rule 2: Break-Even ─────────────────────────────────────────────────
        be_trigger = sl_distance * float(self.config["break_even_rr"])
        if profit_price >= be_trigger and pos.sl != 0:
            buffer    = float(self.config["be_buffer_pips"]) * point
            new_sl    = pos.price_open + buffer if is_buy else pos.price_open - buffer

            improved  = (is_buy and new_sl > pos.sl) or (not is_buy and new_sl < pos.sl)
            if improved:
                modified = self._modify_sl(pos, mt5, new_sl, symbol_info.digits)
                return {
                    "ticket": pos.ticket,
                    "symbol": pos.symbol,
                    "action": "BREAK_EVEN",
                    "reason": f"Profit {profit_price:.5f} >= {be_trigger:.5f}",
                    "new_sl": round(new_sl, symbol_info.digits),
                    "modified": modified,
                }

        # ── Rule 3: Trailing SL ────────────────────────────────────────────────
        trail_trigger = sl_distance * float(self.config["trail_trigger_rr"])
        if profit_price >= trail_trigger:
            trail_dist = sl_distance * float(self.config["trail_ratio"])

            if is_buy:
                new_sl   = current_price - trail_dist
                improved = new_sl > pos.sl
            else:
                new_sl   = current_price + trail_dist
                improved = pos.sl == 0 or new_sl < pos.sl

            if improved:
                modified = self._modify_sl(pos, mt5, new_sl, symbol_info.digits)
                return {
                    "ticket": pos.ticket,
                    "symbol": pos.symbol,
                    "action": "TRAILING_SL",
                    "reason": f"Profit {profit_price:.5f} >= trail trigger {trail_trigger:.5f}",
                    "new_sl": round(new_sl, symbol_info.digits),
                    "modified": modified,
                }

        # ── No action: return monitoring data ──────────────────────────────────
        return {
            "ticket":      pos.ticket,
            "symbol":      pos.symbol,
            "action":      "HOLDING",
            "profit_price": round(profit_price, 5),
            "profit_usd":   round(pos.profit, 2),
            "hold_hours":   round(hold_hours, 1),
            "sl_distance":  round(sl_distance, 5),
        }

    def _close_position(self, pos, mt5, reason: str) -> bool:
        """Market-close a position."""
        try:
            tick       = mt5.symbol_info_tick(pos.symbol)
            if not tick:
                return False
            is_buy     = pos.type == 0
            close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
            close_price = tick.bid if is_buy else tick.ask

            request = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       pos.symbol,
                "volume":       pos.volume,
                "type":         close_type,
                "position":     pos.ticket,
                "price":        close_price,
                "deviation":    20,
                "magic":        pos.magic,
                "comment":      f"PM:{reason[:15]}",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            return bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)
        except Exception as e:
            logger.error(f"PositionMonitor._close_position error: {e}")
            return False

    def _modify_sl(self, pos, mt5, new_sl: float, digits: int) -> bool:
        """Modify stop-loss of an open position."""
        try:
            request = {
                "action":   mt5.TRADE_ACTION_SLTP,
                "symbol":   pos.symbol,
                "position": pos.ticket,
                "sl":       round(new_sl, digits),
                "tp":       pos.tp,
            }
            result = mt5.order_send(request)
            return bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)
        except Exception as e:
            logger.error(f"PositionMonitor._modify_sl error: {e}")
            return False

    def _record_close(self, pos):
        """Notify Circuit Breaker when a position is force-closed."""
        try:
            from intelligence.circuit_breaker import get_circuit_breaker
            cb = get_circuit_breaker()
            is_win = pos.profit > 0
            cb.record_trade_result(pnl_usd=float(pos.profit), is_win=is_win)
            logger.info(
                f"PositionMonitor: recorded close #{pos.ticket} "
                f"pnl=${pos.profit:.2f} win={is_win}"
            )
        except Exception as e:
            logger.warning(f"PositionMonitor._record_close: {e}")
