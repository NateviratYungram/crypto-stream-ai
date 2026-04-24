import logging
from typing import Dict, Any, List
from intelligence.mt5_connector import get_mt5_account_info, initialize_mt5
from intelligence.brain import get_brain_state
from intelligence.tools.market_tools import get_portfolio_analytics

logger = logging.getLogger(__name__)

# Institutional Thresholds
CRITICAL_DRAWDOWN_PCT = 5.0  # Alert if equity drops 5% below balance
MIN_MARGIN_LEVEL = 500.0    # Alert if margin level drops below 500%

def perform_system_heartbeat() -> Dict[str, Any]:
    """
    Background 'Active Guardian' check.
    Analyzes account health, risk, and aligns with AI Working Memory.
    """
    logger.info("Heartbeat: Starting autonomous health check...")

    if not initialize_mt5():
        return {"status": "ERROR", "message": "MT5 Terminal Disconnected"}

    # 1. Account Health Check
    account = get_mt5_account_info()
    balance = account.get("balance", 0)
    equity = account.get("equity", 0)
    margin_level = account.get("margin_level", 0)

    drawdown_pct = ((balance - equity) / balance * 100) if balance > 0 else 0

    alerts = []
    if drawdown_pct >= CRITICAL_DRAWDOWN_PCT:
        alerts.append(f"CRITICAL DRAWDOWN: {drawdown_pct:.2f}% (Limit: {CRITICAL_DRAWDOWN_PCT}%)")

    if margin_level > 0 and margin_level < MIN_MARGIN_LEVEL:
        alerts.append(f"MARGIN WARNING: {margin_level:.2f}% (Safety: {MIN_MARGIN_LEVEL}%)")

    # 2. Portfolio Concentration Check
    analytics = get_portfolio_analytics()
    if "risk_warnings" in analytics:
        alerts.extend(analytics["risk_warnings"])

    # 3. Brain Alignment
    brain = get_brain_state()
    current_plan = brain.get("frontal_lobe", "")

    # 4. Snapshot (Integrated)
    from intelligence.snapshots import take_account_snapshot
    take_account_snapshot()

    status = "HEALTHY" if not alerts else "WARNING"

    report = {
        "status": status,
        "timestamp": brain.get("last_updated"),
        "metrics": {
            "equity": equity,
            "drawdown_pct": round(drawdown_pct, 2),
            "margin_level": round(margin_level, 2)
        },
        "alerts": alerts,
        "current_focus": current_plan
    }

    if alerts:
        logger.warning(f"Heartbeat: System Alert! {alerts}")
    else:
        logger.info("Heartbeat: All systems normal.")

    return report

if __name__ == "__main__":
    # Can be run as a standalone script via Cron
    import json
    print(json.dumps(perform_system_heartbeat(), indent=2))
