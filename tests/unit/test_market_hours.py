import datetime

import pytz

from intelligence.utils import market_hours


def test_is_us_market_holiday_covers_static_and_floating_dates():
    assert market_hours.is_us_market_holiday(datetime.date(2026, 1, 1)) is True
    assert market_hours.is_us_market_holiday(datetime.date(2026, 1, 19)) is True
    assert market_hours.is_us_market_holiday(datetime.date(2026, 2, 16)) is True
    assert market_hours.is_us_market_holiday(datetime.date(2026, 5, 25)) is True
    assert market_hours.is_us_market_holiday(datetime.date(2026, 9, 7)) is True
    assert market_hours.is_us_market_holiday(datetime.date(2026, 11, 26)) is True
    assert market_hours.is_us_market_holiday(datetime.date(2026, 4, 3)) is True
    assert market_hours.is_us_market_holiday(datetime.date(2026, 5, 26)) is False


def test_forex_market_state_open_and_closed_windows():
    open_now = datetime.datetime(2026, 5, 25, 10, 0, tzinfo=pytz.UTC)
    closed_now = datetime.datetime(2026, 5, 23, 22, 0, tzinfo=pytz.UTC)

    open_state = market_hours._forex_market_state(open_now)
    closed_state = market_hours._forex_market_state(closed_now)

    assert open_state["status"] == "OPEN"
    assert open_state["next_event"] == "CLOSE"
    assert closed_state["status"] == "CLOSED"
    assert closed_state["next_event"] == "OPEN"


def test_next_stock_open_handles_same_day_and_skips_holiday(monkeypatch):
    same_day = datetime.datetime(2026, 5, 26, 12, 0, tzinfo=pytz.UTC)
    next_open = market_hours._next_stock_open(same_day, is_holiday_today=False)
    assert next_open.hour == 13 and next_open.minute == 30

    holiday = datetime.datetime(2026, 7, 3, 21, 0, tzinfo=pytz.UTC)

    def fake_holiday(day):
        return day in {datetime.date(2026, 7, 6)}

    monkeypatch.setattr(market_hours, "is_us_market_holiday", fake_holiday)
    delayed_open = market_hours._next_stock_open(holiday, is_holiday_today=False)

    assert delayed_open.date() == datetime.date(2026, 7, 7)
    assert delayed_open.hour == 13 and delayed_open.minute == 30


def test_stocks_market_state_open_closed_and_holiday(monkeypatch):
    monkeypatch.setattr(market_hours, "is_us_market_holiday", lambda _: False)
    open_now = datetime.datetime(2026, 5, 26, 15, 0, tzinfo=pytz.UTC)
    closed_now = datetime.datetime(2026, 5, 26, 22, 0, tzinfo=pytz.UTC)

    open_state = market_hours._stocks_market_state(open_now)
    closed_state = market_hours._stocks_market_state(closed_now)

    assert open_state["status"] == "OPEN"
    assert open_state["next_event"] == "CLOSE"
    assert closed_state["status"] == "CLOSED"
    assert closed_state["next_event"] == "OPEN"

    monkeypatch.setattr(market_hours, "is_us_market_holiday", lambda day: day == datetime.date(2026, 7, 4))
    holiday_now = datetime.datetime(2026, 7, 4, 15, 0, tzinfo=pytz.UTC)
    holiday_state = market_hours._stocks_market_state(holiday_now)
    assert holiday_state["status"] in {"HOLIDAY", "CLOSED"}


def test_get_market_status_data_uses_supplied_timestamp():
    now_utc = datetime.datetime(2026, 5, 26, 15, 0, tzinfo=pytz.UTC)

    payload = market_hours.get_market_status_data(now_utc=now_utc)

    assert payload["crypto"]["status"] == "OPEN"
    assert payload["forex"]["status"] == "OPEN"
    assert payload["timestamp_utc"] == now_utc.isoformat()
