import asyncio
import logging
from typing import Any, Callable

from intelligence.mt5_connector import mt5_modify_position
from intelligence.tools.market_tools import get_market_analysis
from services.notification_service import NotificationService

logger = logging.getLogger(__name__)


def _asset_class_for_symbol(symbol: str) -> str:
    return "CRYPTO" if symbol in ["BTC", "ETH", "SOL"] else "MACRO"


def _is_high_confidence_opportunity(analysis: dict[str, Any]) -> bool:
    whale = analysis.get("whale_pulse", {})
    ml = float(analysis.get("win_probability", 0) or 0)
    return (ml >= 0.80) or (bool(whale.get("injections", False)) and ml >= 0.70)


def _detect_counter_wall_threat(position, whale: dict[str, Any], mt5_module) -> bool:
    current_price = position.price_current
    entry_price = position.price_open
    is_buy = position.type == mt5_module.POSITION_TYPE_BUY

    if is_buy:
        return any(
            float(wall["price"]) < current_price and float(wall["price"]) > entry_price
            for wall in whale.get("walls", {}).get("sell", [])
        )
    return any(
        float(wall["price"]) > current_price and float(wall["price"]) < entry_price
        for wall in whale.get("walls", {}).get("buy", [])
    )


def _is_position_in_profit(position, mt5_module) -> bool:
    is_buy = position.type == mt5_module.POSITION_TYPE_BUY
    return position.price_current > position.price_open if is_buy else position.price_current < position.price_open


def _already_at_break_even(position, mt5_module) -> bool:
    if not position.sl:
        return False
    is_buy = position.type == mt5_module.POSITION_TYPE_BUY
    return (position.sl >= position.price_open) if is_buy else (position.sl <= position.price_open)


class AlphaSentinel:
    """
    Alex's proactive monitoring core.
    Scans for institutional setups and actively guards open trades.
    """

    def __init__(
        self,
        interval_seconds: int = 900,
        notifier: Any | None = None,
        analysis_fn: Callable[..., dict[str, Any]] | None = None,
        modify_position_fn: Callable[..., dict[str, Any]] | None = None,
        mt5_loader: Callable[[], Any] | None = None,
    ):
        self.interval = interval_seconds
        self.notifier = notifier or NotificationService()
        self.analysis_fn = analysis_fn or get_market_analysis
        self.modify_position_fn = modify_position_fn or mt5_modify_position
        self.mt5_loader = mt5_loader or self._default_mt5_loader
        self.target_symbols = ["BTC", "ETH", "SOL", "GOLD", "OIL", "NASDAQ", "SP500"]
        self.active_scans = {}

    def _default_mt5_loader(self):
        import MetaTrader5 as mt5

        return mt5

    async def _run_analysis(self, symbol: str, timeframe: str, asset_class: str) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.analysis_fn, symbol, timeframe, asset_class)

    async def run(self):
        """Main Sentinel loop."""
        logger.info("Alpha Sentinel active. Interval: %ss", self.interval)
        while True:
            try:
                await self.scan_for_alpha()
                await self.guard_active_trades()
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("AlphaSentinel: Loop error: %s", e)
                await asyncio.sleep(60)

    async def scan_for_alpha(self):
        """Scans target symbols for institutional-confluence setups."""
        logger.info("Sentinel: Scanning for alpha opportunities...")
        for symbol in self.target_symbols:
            try:
                analysis = await self._run_analysis(symbol, "15m", _asset_class_for_symbol(symbol))
                if _is_high_confidence_opportunity(analysis) and analysis.get("signal") in ["BUY", "SELL"]:
                    await self.notify_alpha(symbol, analysis)
            except Exception as e:
                logger.error("Sentinel: Failed to scan %s: %s", symbol, e)

    async def guard_active_trades(self):
        """Monitors open MT5 positions and moves SL to break-even when threatened."""
        try:
            try:
                mt5 = self.mt5_loader()
            except ImportError:
                logger.warning("Sentinel: MetaTrader5 not available. Guarding skipped.")
                return

            if not mt5.initialize():
                logger.warning("Sentinel: Failed to initialize MT5. Guarding skipped.")
                return

            positions = mt5.positions_get()
            if not positions:
                return

            for pos in positions:
                symbol = pos.symbol
                ticket = pos.ticket
                analysis = await self._run_analysis(symbol, "15m", "AUTO")
                whale = analysis.get("whale_pulse", {})
                threat_detected = _detect_counter_wall_threat(pos, whale, mt5)
                is_in_profit = _is_position_in_profit(pos, mt5)
                already_at_be = _already_at_break_even(pos, mt5)

                if threat_detected and is_in_profit and not already_at_be:
                    result = self.modify_position_fn(ticket=ticket, sl=pos.price_open, tp=pos.tp or 0.0)
                    if result.get("status") == "SUCCESS":
                        msg = (
                            f"*RISK GUARDIAN ACTIONED*\n"
                            f"Symbol: {symbol} (Ticket: {ticket})\n"
                            f"Threat: Large whale counter-wall detected.\n"
                            f"Action: Stop Loss moved to break-even at {pos.price_open:.5f}."
                        )
                    else:
                        msg = (
                            f"*RISK GUARDIAN ALERT*\n"
                            f"Symbol: {symbol} (Ticket: {ticket})\n"
                            f"Threat: Large whale counter-wall detected.\n"
                            f"Action failed: could not move Stop Loss to break-even.\n"
                            f"Reason: {result.get('comment') or result.get('error') or 'unknown'}"
                        )
                    await self.notifier.broadcast(msg)
        except Exception as e:
            logger.error("Sentinel: Guarding failed: %s", e)

    async def notify_alpha(self, symbol: str, analysis: dict):
        """Broadcasts a high-confluence opportunity."""
        ml = analysis.get("win_probability", 0)
        signal = analysis.get("signal", "HOLD")
        bias = analysis.get("whale_pulse", {}).get("bias", "NEUTRAL")

        msg = (
            f"*ALPHA SENTINEL TRIGGER*\n"
            f"Symbol: {symbol} | Signal: {signal}\n"
            f"Institutional Bias: {bias}\n"
            f"ML Win Prob: {ml:.1%}\n\n"
            f"Check Chat: 'Analyze {symbol} and build a trade plan'"
        )
        await self.notifier.broadcast(msg)


alpha_sentinel = AlphaSentinel()
