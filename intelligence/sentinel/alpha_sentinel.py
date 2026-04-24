import asyncio
import logging

from intelligence.mt5_connector import mt5_modify_position
from intelligence.tools.market_tools import get_market_analysis
from services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class AlphaSentinel:
    """
    Alex's proactive monitoring core.
    Scans for institutional setups and actively guards open trades.
    """

    def __init__(self, interval_seconds: int = 900):
        self.interval = interval_seconds
        self.notifier = NotificationService()
        self.target_symbols = ["BTC", "ETH", "SOL", "GOLD", "USOIL", "NAS100", "SPX"]
        self.active_scans = {}

    async def run(self):
        """Main Sentinel loop."""
        logger.info(f"Alpha Sentinel active. Interval: {self.interval}s")
        while True:
            try:
                await self.scan_for_alpha()
                await self.guard_active_trades()
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"AlphaSentinel: Loop error: {e}")
                await asyncio.sleep(60)

    async def scan_for_alpha(self):
        """Scans target symbols for institutional-confluence setups."""
        logger.info("Sentinel: Scanning for alpha opportunities...")
        for symbol in self.target_symbols:
            try:
                asset_class = "CRYPTO" if symbol in ["BTC", "ETH", "SOL"] else "MACRO"
                loop = asyncio.get_event_loop()
                analysis = await loop.run_in_executor(
                    None,
                    get_market_analysis,
                    symbol,
                    "15m",
                    asset_class,
                )

                whale = analysis.get("whale_pulse", {})
                ml = analysis.get("win_probability", 0)
                high_conf = (ml >= 0.80) or (whale.get("injections", False) and ml >= 0.70)

                if high_conf and analysis.get("signal") in ["BUY", "SELL"]:
                    await self.notify_alpha(symbol, analysis)
            except Exception as e:
                logger.error(f"Sentinel: Failed to scan {symbol}: {e}")

    async def guard_active_trades(self):
        """Monitors open MT5 positions and moves SL to break-even when threatened."""
        try:
            try:
                import MetaTrader5 as mt5
            except ImportError:
                logger.warning("Sentinel: MetaTrader5 not available. Guarding skipped.")
                return

            if not mt5.initialize():
                logger.warning("Sentinel: Failed to initialize MT5. Guarding skipped.")
                return

            positions = mt5.positions_get()
            if not positions:
                return

            loop = asyncio.get_event_loop()
            for pos in positions:
                symbol = pos.symbol
                ticket = pos.ticket
                analysis = await loop.run_in_executor(
                    None,
                    get_market_analysis,
                    symbol,
                    "15m",
                    "AUTO",
                )

                whale = analysis.get("whale_pulse", {})
                current_price = pos.price_current
                entry_price = pos.price_open
                is_buy = pos.type == mt5.POSITION_TYPE_BUY
                is_in_profit = current_price > entry_price if is_buy else current_price < entry_price

                if is_buy:
                    threat_detected = any(
                        float(wall["price"]) < current_price and float(wall["price"]) > entry_price
                        for wall in whale.get("walls", {}).get("sell", [])
                    )
                else:
                    threat_detected = any(
                        float(wall["price"]) > current_price and float(wall["price"]) < entry_price
                        for wall in whale.get("walls", {}).get("buy", [])
                    )

                already_at_break_even = bool(
                    pos.sl and ((pos.sl >= entry_price) if is_buy else (pos.sl <= entry_price))
                )

                if threat_detected and is_in_profit and not already_at_break_even:
                    result = mt5_modify_position(ticket=ticket, sl=entry_price, tp=pos.tp or 0.0)
                    if result.get("status") == "SUCCESS":
                        msg = (
                            f"*RISK GUARDIAN ACTIONED*\n"
                            f"Symbol: {symbol} (Ticket: {ticket})\n"
                            f"Threat: Large whale counter-wall detected.\n"
                            f"Action: Stop Loss moved to break-even at {entry_price:.5f}."
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
            logger.error(f"Sentinel: Guarding failed: {e}")

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
