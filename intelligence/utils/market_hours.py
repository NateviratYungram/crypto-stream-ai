import datetime
from typing import Any, Dict

import pytz

_GOOD_FRIDAYS = {
    2024: (3, 29),
    2025: (4, 18),
    2026: (4, 3),
}


def is_us_market_holiday(date_obj: datetime.date) -> bool:
    """
    Returns True if the given date is a US Stock Market (NYSE/NASDAQ) Holiday.
    Covering 2024-2026.
    """
    year = date_obj.year
    month = date_obj.month
    day = date_obj.day

    holidays = {
        (1, 1),   # New Year's Day
        (6, 19),  # Juneteenth
        (7, 4),   # Independence Day
        (12, 25),  # Christmas Day
    }

    if (month, day) in holidays:
        return True
    if month == 1 and date_obj.weekday() == 0 and 15 <= day <= 21:
        return True
    if month == 2 and date_obj.weekday() == 0 and 15 <= day <= 21:
        return True
    if month == 5 and date_obj.weekday() == 0 and day > 24:
        return True
    if month == 9 and date_obj.weekday() == 0 and day <= 7:
        return True
    if month == 11 and date_obj.weekday() == 3 and 22 <= day <= 28:
        return True
    if year in _GOOD_FRIDAYS and (month, day) == _GOOD_FRIDAYS[year]:
        return True
    return False


def _forex_market_state(now_utc: datetime.datetime) -> Dict[str, Any]:
    """Return the current 24/5 forex market state in UTC."""
    weekday = now_utc.weekday()
    hour = now_utc.hour
    target = now_utc.replace(hour=21, minute=0, second=0, microsecond=0)

    if (weekday == 6 and hour >= 21) or weekday < 4 or (weekday == 4 and hour < 21):
        days_to_fri = (4 - weekday) % 7
        target = target + datetime.timedelta(days=days_to_fri)
        return {
            "status": "OPEN",
            "next_event": "CLOSE",
            "seconds_remaining": int((target - now_utc).total_seconds()),
            "event_time": target.isoformat(),
        }

    days_to_sun = (6 - weekday) % 7
    target = target + datetime.timedelta(days=days_to_sun)
    if target < now_utc:
        target += datetime.timedelta(days=7)
    return {
        "status": "CLOSED",
        "next_event": "OPEN",
        "seconds_remaining": int((target - now_utc).total_seconds()),
        "event_time": target.isoformat(),
    }


def _next_stock_open(now_utc: datetime.datetime, is_holiday_today: bool) -> datetime.datetime:
    """Find the next non-holiday weekday market open in UTC."""
    weekday = now_utc.weekday()
    time_val = now_utc.hour * 100 + now_utc.minute
    if weekday < 5 and time_val < 1330 and not is_holiday_today:
        return now_utc.replace(hour=13, minute=30, second=0, microsecond=0)

    days_to_add = 1
    while True:
        next_day = now_utc + datetime.timedelta(days=days_to_add)
        if next_day.weekday() < 5 and not is_us_market_holiday(next_day.date()):
            return next_day.replace(hour=13, minute=30, second=0, microsecond=0)
        days_to_add += 1


def _stocks_market_state(now_utc: datetime.datetime) -> Dict[str, Any]:
    """Return US stocks market state in UTC with holiday-aware scheduling."""
    today_utc = now_utc.date()
    weekday = now_utc.weekday()
    time_val = now_utc.hour * 100 + now_utc.minute
    is_holiday = is_us_market_holiday(today_utc)

    if not is_holiday and weekday < 5 and 1330 <= time_val < 2000:
        target = now_utc.replace(hour=20, minute=0, second=0, microsecond=0)
        return {
            "status": "OPEN",
            "next_event": "CLOSE",
            "seconds_remaining": int((target - now_utc).total_seconds()),
            "event_time": target.isoformat(),
        }

    target = _next_stock_open(now_utc, is_holiday)
    return {
        "status": "HOLIDAY" if is_holiday and weekday < 5 else "CLOSED",
        "next_event": "OPEN",
        "seconds_remaining": int((target - now_utc).total_seconds()),
        "event_time": target.isoformat(),
    }


def get_market_status_data(now_utc: datetime.datetime | None = None) -> Dict[str, Any]:
    """
    Calculates the current status (OPEN/CLOSED) and time remaining
    to the next state change for major market regimes.
    """
    now_utc = now_utc or datetime.datetime.now(pytz.UTC)
    crypto = {
        "status": "OPEN",
        "next_event": None,
        "seconds_remaining": None,
        "label": "24/7",
    }
    return {
        "crypto": crypto,
        "forex": _forex_market_state(now_utc),
        "stocks": _stocks_market_state(now_utc),
        "timestamp_utc": now_utc.isoformat(),
    }
