import asyncio
import logging
import json
from datetime import datetime, timezone
from typing import List, Dict, Any

from intelligence.tools.market_tools import get_market_analysis, get_mt5_account_info
from intelligence.mt5_connector import mt5_modify_position
from services.notification_service import NotificationService
from intelligence.constants import NASDAQ_100_TICKERS, SP500_TICKERS

logger = logging.getLogger(__name__)

class AlphaSentinel:
    """
    Alex's Proactive Monitoring Core.
    Scans for institutional setups and guards active trades autonomously.
    """
    def __init__(self, interval_seconds: int = 900): # 15 minutes default
        self.interval = interval_seconds
        self.notifier = NotificationService()
        self.target_symbols = ["BTC", "ETH", "SOL", "GOLD", "USOIL", "NAS100", "SPX"]
        self.active_scans = {}

    async def run(self):
        """Main Sentinel loop."""
        logger.info(f"🛰️ Alpha Sentinel active. Interval: {self.interval}s")
        while True:
            try:
                # 1. Proactive Opportunity Scan
                await self.scan_for_alpha()

                # 2. Risk Guardian: Monitor active trades for SL adjustments
                await self.guard_active_trades()

                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"AlphaSentinel: Loop error: {e}")
                await asyncio.sleep(60)

    async def scan_for_alpha(self):
        """Scans target symbols for 'Institutional Confluence'."""
        logger.info("📡 Sentinel: Scanning for Alpha Opportunities...")
        for symbol in self.target_symbols:
            try:
                # Determine asset class
                asset_class = "CRYPTO" if symbol in ["BTC", "ETH", "SOL"] else "MACRO"

                # Perform full analysis
                # Run in thread pool to avoid blocking async loop
                loop = asyncio.get_event_loop()
                analysis = await loop.run_in_executor(
                    None,
                    get_market_analysis,
                    symbol, "15m", asset_class
                )

                # Check for "Sentinel Trigger"
                # Conditions: ML Prob > 80% AND Whale Injection Detected OR Major SMC Breakout
                whale = analysis.get("whale_pulse", {})
                ml = analysis.get("win_probability", 0)
                smc = analysis.get("indicator_summary", {}).get("smart_money", {})

                high_conf = (ml >= 0.80) or (whale.get("injections", False) and ml >= 0.70)

                if high_conf and analysis.get("signal") in ["BUY", "SELL"]:
                    await self.notify_alpha(symbol, analysis)

            except Exception as e:
                logger.error(f"Sentinel: Failed to scan {symbol}: {e}")

    async def guard_active_trades(self):
        """Monitors open MT5 positions and suggests SL modifications."""
        try:
            # Note: This requires get_active_trades or similar.
            # For now, we manually fetch from MT5
            try:
                import MetaTrader5 as mt5
            except ImportError:
                logger.warning("Sentinel: MetaTrader5 not available. Guarding skipped.")
                return

            if not mt5.initialize():
                return

            positions = mt5.positions_get()
            if not positions:
                return

            for pos in positions:
                symbol = pos.symbol
                ticket = pos.ticket

                # Fetch fresh Whale Pulse for this position
                loop = asyncio.get_event_loop()
                analysis = await loop.run_in_executor(None, get_market_analysis, symbol, "15m", "AUTO")

                whale = analysis.get("whale_pulse", {})
                current_price = pos.price_current
                entry_price = pos.price_open

                # Logic: If position is in profit and a Large Whale Wall forms at/near Entry
                # PROACTIVE BE (Break Even) Trigger
                profit_pips = abs(current_price - entry_price)

                # Simple example: if in profit and Whale Wall detected opposite to trade
                threat_detected = False
                if pos.type == mt5.POSITION_TYPE_BUY:
                    # Check SELL walls above
                    threat_detected = any(float(w['price']) < current_price and float(w['price']) > entry_price for w in whale.get("walls", {}).get("sell", []))
                else: # SHORT
                    # Check BUY walls below
                    threat_detected = any(float(w['price']) > current_price and float(w['price']) < entry_price for w in whale.get("walls", {}).get("buy", []))

                if threat_detected and pos.sl == 0:
                    msg = (
                        f"🚨 *RISK GUARDIAN ALERT*\n"
                        f"Symbol: {symbol} (Ticket: {ticket})\n"
                        f"Threat: Large Whale Counter-Wall detected.\n"
                        f"Action: Protective Stop Loss (BE) recommended."
                    )
                    await self.notifier.broadcast(msg)
                    # Future: mt5_modify_position(ticket, sl=entry_price)

        except Exception as e:
            logger.error(f"Sentinel: Guarding failed: {e}")

    async def notify_alpha(self, symbol: str, analysis: dict):
        """Broadcasts a high-confluence opportunity."""
        ml = analysis.get("win_probability", 0)
        signal = analysis.get("signal", "HOLD")
        bias = analysis.get("whale_pulse", {}).get("bias", "NEUTRAL")

        msg = (
            f"🚀 *ALPHA SENTINEL TRIGGER*\n"
            f"Symbol: {symbol} | Signal: {signal}\n"
            f"Institutional Bias: {bias}\n"
            f"ML Win Prob: {ml:.1%}\n\n"
            f"Check Chat: 'วิเคราะห์ {symbol} ขอแผนเทรด'"
        )
        await self.notifier.broadcast(msg)

alpha_sentinel = AlphaSentinel()
