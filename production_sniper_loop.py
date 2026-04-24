import time
import logging
import sys
import os
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.append(str(Path.cwd()))

from intelligence.ml.signal_scanner import scan_for_high_probability_signals, _send_telegram
from intelligence.brain import update_brain_state
from intelligence.utils.market_hours import get_market_status_data

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("sniper_scanner.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("SniperLoop")

def run_loop():
    logger.info("==================================================")
    logger.info("   🎯 CRYPTOSTREAM AI: SNIPER MODE ACTIVE")
    logger.info("   [Model: Neural V8 Hybrid Attention]")
    logger.info("   [Threshold: 80%+] [Interval: 15 Minutes]")
    logger.info("==================================================")
    
    update_brain_state(
        memory="Neural V8 Sniper Mode started. Scanning 25 asset/TF pairs every 15m.",
        emotion="FOCUSED"
    )

    last_market_status = None

    while True:
        try:
            # ── Market Status Monitoring ──────────────────
            market_data = get_market_status_data()
            current_status = market_data.get("forex", {}).get("status")
            
            if last_market_status and current_status != last_market_status:
                msg = f"🔔 *MARKET STATUS UPDATE*\n\nForex/Commodities status changed to: *{current_status}*"
                if current_status == "CLOSED":
                    msg += "\n💤 _AI scanning will continue but execution is restricted._"
                else:
                    msg += "\n⚡ _Liquidity returning. Neural V8 scanning at full capacity._"
                _send_telegram(msg)
            
            last_market_status = current_status

            now = datetime.now()
            logger.info(f"--- Starting Scan Cycle: {now.strftime('%Y-%m-%d %H:%M:%S')} ---")
            
            # Execute scanner
            results = scan_for_high_probability_signals(threshold=80.0)
            
            found = results.get("found", 0)
            scanned = results.get("scanned", 0)
            
            if found > 0:
                logger.info(f"🎯 SNIPER HIT: Found {found} high-probability signals!")
                update_brain_state(
                    memory=f"Detected {found} Sniper signals. Alerts sent to Telegram.",
                    emotion="EXCITED"
                )
            else:
                logger.info(f"Scanning complete. No Sniper signals found (Scanned {scanned} pairs).")
                update_brain_state(
                    memory=f"Last scan found no 80%+ signals. Market is neutral.",
                    emotion="CALM"
                )

            # Wait for 15 minutes
            logger.info("Waiting 15 minutes for next cycle...")
            time.sleep(15 * 60)
            
        except KeyboardInterrupt:
            logger.info("Sniper Mode stopped by user.")
            update_brain_state(memory="Sniper Mode deactivated.", emotion="NEUTRAL")
            break
        except Exception as e:
            logger.error(f"Error in Sniper Loop: {e}")
            time.sleep(60) # Wait a bit before retrying

if __name__ == "__main__":
    # Force UTF-8 for Windows
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    run_loop()
