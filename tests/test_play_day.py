from datetime import date

from padel_bot.bot.keyboards import BOOKING_WINDOW_DAYS, parse_day
from padel_bot.domain import WHOLE_DAY, TimeRange
from tests.conftest import dt

TODAY = date(2026, 9, 15)


def test_play_day_boundary_at_six():
    assert WHOLE_DAY.contains(TODAY, dt("2026-09-15T06:00:00"))
    assert not WHOLE_DAY.contains(TODAY, dt("2026-09-15T05:59:00"))
    assert WHOLE_DAY.contains(TODAY, dt("2026-09-16T05:59:00"))
    assert not WHOLE_DAY.contains(TODAY, dt("2026-09-16T06:00:00"))


def test_evening_range_crosses_midnight():
    evening = TimeRange(17, 30)
    assert evening.contains(TODAY, dt("2026-09-16T01:00:00"))
    assert not evening.contains(TODAY, dt("2026-09-15T16:59:00"))


def test_parse_day_accepts_booking_window_only():
    assert parse_day("20260915", TODAY) == TODAY
    last = date(2026, 9, 15 + BOOKING_WINDOW_DAYS - 1)
    assert parse_day(f"{last:%Y%m%d}", TODAY) == last
    assert parse_day("20260922", TODAY) is None  # one day past the window
    assert parse_day("20260914", TODAY) is None  # yesterday's message
    assert parse_day("20991231", TODAY) is None


def test_parse_day_rejects_garbage():
    for value in ("", "abc", "2026-09-15", "20261345"):
        assert parse_day(value, TODAY) is None
