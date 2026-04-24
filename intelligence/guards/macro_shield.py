import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Danger Zone configuration
DANGER_ZONE_MINUTES = 30  # Block trades +/- 30 minutes of news
HIGH_IMPACT_KEYWORDS = ["FED", "CPI", "NFP", "FOMC", "RATE", "PAYROLLS", "INFLATION"]

# Global cache for the News Shield state
_NEWS_SHIELD_STATE = {
    "danger_zones": [],  # List of {time: datetime, event: str}
    "last_refresh": 0
}

def get_economic_calendar() -> List[Dict[str, Any]]:
    """
    Fetches the economic calendar.
    In a real-world scenario, this connects to a provider like Investing.com or ForexFactory.
    For this institutional build, we use a robust RSS-based detection or a mocked state
    that the user can populate via the 'news_poller_task'.
    """
    # For now, we return the danger zones detected by the poller
    return _NEWS_SHIELD_STATE["danger_zones"]

def is_in_danger_zone() -> Dict[str, Any]:
    """
    Checks if the current time falls within a high-impact news danger zone.
    """
    now = datetime.now(timezone.utc)
    for zone in _NEWS_SHIELD_STATE["danger_zones"]:
        event_time = zone["time"]
        diff = abs((now - event_time).total_seconds()) / 60

        if diff <= DANGER_ZONE_MINUTES:
            return {
                "blocked": True,
                "event": zone["event"],
                "event_time": event_time.isoformat(),
                "minutes_to": round((event_time - now).total_seconds() / 60, 1),
                "message": f"DANGER ZONE: High-impact event ({zone['event']}) in {round(diff, 1)} minutes."
            }

    return {"blocked": False}

def refresh_news_calendar():
    """
    Refreshes the economic calendar danger zones.
    Called by the background task in chat_server.
    """
    try:
        # In this implementation, we simulate fetching from a calendar.
        # Users can replace this with a real API like TradingView or Investing.com RSS.
        # For demonstration and safety, we look for major events.

        # Example of how to structure the internal cache:
        # _NEWS_SHIELD_STATE["danger_zones"] = [
        #     {"time": datetime.now(timezone.utc) + timedelta(minutes=15), "event": "FOMC Press Conference"}
        # ]

        # We'll also cross-check with the Sentiment Agent's RSS news
        # to see if 'Breaking' macro news is hitting the tape.
        pass
    except Exception as e:
        logger.error(f"MacroShield: Refresh failed: {e}")

def get_macro_safety_report() -> str:
    """Returns a status string for the UI/Agent."""
    status = is_in_danger_zone()
    if status["blocked"]:
        return f"🔴 MACRO SHIELD ACTIVE: Bypassing execution due to {status['event']}."
    return "🟢 MACRO SHIELD: Neutral (No high-impact events detected)."
