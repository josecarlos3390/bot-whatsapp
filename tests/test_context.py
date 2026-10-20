from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

from app import context


def test_time_greetings():
    base = datetime(2026, 10, 20, tzinfo=timezone(timedelta(hours=-4)))
    assert context.greeting(base.replace(hour=7)) == "Buenos días"
    assert context.greeting(base.replace(hour=14)) == "Buenas tardes"
    assert context.greeting(base.replace(hour=21)) == "Buenas noches"
    assert context.greeting(base.replace(hour=2)) == "Buenas noches"


def test_holiday_calendar():
    assert context.holiday_today(date(2026, 12, 25)) == "Navidad"
    assert context.holiday_today(date(2026, 9, 24)) == "Día de Santa Cruz"
    assert context.holiday_today(date(2026, 10, 20)) is None
