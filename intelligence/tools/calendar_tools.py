import requests
import xml.etree.ElementTree as ET
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

class CalendarTools:
    """
    Fetches Economic Calendar from ForexFactory.
    Filters for high-impact (Red) news events to protect trading executions.
    """
    def __init__(self):
        self.feed_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
        self._cache = []
        self._last_fetch = None
        self._cache_ttl = timedelta(hours=1)
        
    def fetch_calendar(self):
        """Fetches and caches the weekly XML feed."""
        now = datetime.now(timezone.utc)
        if self._cache and self._last_fetch and (now - self._last_fetch) < self._cache_ttl:
            return self._cache
            
        try:
            r = requests.get(self.feed_url, timeout=10)
            if r.status_code == 200:
                root = ET.fromstring(r.text)
                events = []
                for ev in root.findall("event"):
                    # Date format: 04-20-2026, Time: 8:30am (Eastern Time by default)
                    # For simplicity, we just store raw strings and parse relative times later if needed,
                    # or apply simple string matching for 'today'.
                    events.append({
                        "title": ev.find("title").text if ev.find("title") is not None else "",
                        "country": ev.find("country").text if ev.find("country") is not None else "",
                        "date": ev.find("date").text if ev.find("date") is not None else "",
                        "time": ev.find("time").text if ev.find("time") is not None else "",
                        "impact": ev.find("impact").text if ev.find("impact") is not None else "Low",
                        "forecast": ev.find("forecast").text if ev.find("forecast") is not None else "",
                        "previous": ev.find("previous").text if ev.find("previous") is not None else ""
                    })
                self._cache = events
                self._last_fetch = now
                logger.info(f"CalendarTools: Fetched {len(events)} events from ForexFactory.")
                return events
            else:
                logger.error(f"CalendarTools: Failed to fetch XML. Status: {r.status_code}")
                return []
        except Exception as e:
            logger.error(f"CalendarTools: Exception fetching calendar: {e}")
            return []

    def get_upcoming_high_impact(self, currencies: list[str]) -> list[dict]:
        """
        Returns High impact events for today/tomorrow for specific currencies.
        Currencies should be ["USD", "EUR"], etc.
        """
        events = self.fetch_calendar()
        if not events:
            return []
            
        # Get today's date in FF format (MM-DD-YYYY)
        # Note: ForexFactory timezone can be tricky. We do a loose match.
        today_str = datetime.now().strftime("%m-%d-%Y")
        
        filtered = []
        for ev in events:
            if ev["impact"] == "High" and ev["country"] in currencies:
                # Basic filter: Only include if date is today
                # In a full prod environment, we would translate US ET to UTC.
                if ev["date"] == today_str:
                    filtered.append(ev)
                    
        return filtered

calendar_engine = CalendarTools()

if __name__ == "__main__":
    print(calendar_engine.get_upcoming_high_impact(["USD", "EUR"]))
