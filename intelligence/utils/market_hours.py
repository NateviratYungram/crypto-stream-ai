import datetime
import pytz
from typing import Dict, Any, Optional

def is_us_market_holiday(date_obj: datetime.date) -> bool:
    """
    Returns True if the given date is a US Stock Market (NYSE/NASDAQ) Holiday.
    Covering 2024-2026.
    """
    year = date_obj.year
    month = date_obj.month
    day = date_obj.day
    
    # Static Holidays
    holidays = [
        (1, 1),   # New Year's Day
        (6, 19),  # Juneteenth
        (7, 4),   # Independence Day
        (12, 25), # Christmas Day
    ]
    
    if (month, day) in holidays:
        return True
        
    # Floating Holidays (Logic approach)
    # MLK Day: 3rd Monday of Jan
    if month == 1 and date_obj.weekday() == 0 and 15 <= day <= 21:
        return True
    
    # Presidents Day: 3rd Monday of Feb
    if month == 2 and date_obj.weekday() == 0 and 15 <= day <= 21:
        return True
        
    # Memorial Day: Last Monday of May
    if month == 5 and date_obj.weekday() == 0 and day > 24:
        return True
        
    # Labor Day: 1st Monday of Sep
    if month == 9 and date_obj.weekday() == 0 and day <= 7:
        return True
        
    # Thanksgiving: 4th Thursday of Nov
    if month == 11 and date_obj.weekday() == 3 and 22 <= day <= 28:
        return True
        
    # Special: Good Friday (Variables)
    good_fridays = {
        2024: (3, 29),
        2025: (4, 18),
        2026: (4, 3)
    }
    if year in good_fridays and (month, day) == good_fridays[year]:
        return True

    return False

def get_market_status_data() -> Dict[str, Any]:
    """
    Calculates the current status (OPEN/CLOSED) and time remaining 
    to the next state change for major market regimes.
    """
    now_utc = datetime.datetime.now(pytz.UTC)
    today_utc = now_utc.date()
    
    # ── CRYPTO ──────────────────────────────────────────────────────────────
    crypto = {
        "status": "OPEN",
        "next_event": None,
        "seconds_remaining": None,
        "label": "24/7"
    }

    # ── FOREX / GOLD (24/5) ────────────────────────────────────────────────
    # Logic: Opens Sunday 21:00 UTC, Closes Friday 21:00 UTC
    forex_status = "CLOSED"
    forex_next = "OPEN"
    forex_target = None
    
    # Day of week: Mon=0, Sun=6
    weekday = now_utc.weekday()
    hour = now_utc.hour
    
    if (weekday == 6 and hour >= 21) or (weekday < 4) or (weekday == 4 and hour < 21):
        forex_status = "OPEN"
        forex_next = "CLOSE"
        days_to_fri = (4 - weekday) % 7
        forex_target = now_utc.replace(hour=21, minute=0, second=0, microsecond=0) + datetime.timedelta(days=days_to_fri)
    else:
        days_to_sun = (6 - weekday) % 7
        forex_target = now_utc.replace(hour=21, minute=0, second=0, microsecond=0) + datetime.timedelta(days=days_to_sun)
        if forex_target < now_utc:
            forex_target += datetime.timedelta(days=7)

    forex_rem = int((forex_target - now_utc).total_seconds()) if forex_target else 0
    forex = {
        "status": forex_status,
        "next_event": forex_next,
        "seconds_remaining": forex_rem,
        "event_time": forex_target.isoformat() if forex_target else None
    }

    # ── US STOCKS (NYSE/NASDAQ) ─────────────────────────────────────────────
    # Logic: Mon-Fri 13:30 - 20:00 UTC, considering Holidays
    stocks_status = "CLOSED"
    stocks_next = "OPEN"
    stocks_target = None
    is_holiday = is_us_market_holiday(today_utc)
    
    time_val = now_utc.hour * 100 + now_utc.minute
    
    # Check if currently open
    if not is_holiday and weekday < 5 and (1330 <= time_val < 2000):
        stocks_status = "OPEN"
        stocks_next = "CLOSE"
        stocks_target = now_utc.replace(hour=20, minute=0, second=0, microsecond=0)
    else:
        # Find next open: Iterate days until we find a non-holiday weekday
        check_date = now_utc
        if weekday < 5 and time_val < 1330 and not is_holiday:
            # Reopens today later
            stocks_target = now_utc.replace(hour=13, minute=30, second=0, microsecond=0)
        else:
            # Need to look ahead
            days_to_add = 1
            while True:
                next_day = now_utc + datetime.timedelta(days=days_to_add)
                next_weekday = next_day.weekday()
                if next_weekday < 5 and not is_us_market_holiday(next_day.date()):
                    stocks_target = next_day.replace(hour=13, minute=30, second=0, microsecond=0)
                    break
                days_to_add += 1

    stocks_rem = int((stocks_target - now_utc).total_seconds()) if stocks_target else 0
    stocks = {
        "status": "HOLIDAY" if is_holiday and weekday < 5 else stocks_status,
        "next_event": stocks_next,
        "seconds_remaining": stocks_rem,
        "event_time": stocks_target.isoformat() if stocks_target else None
    }

    return {
        "crypto": crypto,
        "forex": forex,
        "stocks": stocks,
        "timestamp_utc": now_utc.isoformat()
    }
