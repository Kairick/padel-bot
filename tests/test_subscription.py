"""Subscription card toggles: rules of the subscription model, shown as watch-ui buttons."""

from dataclasses import replace
from datetime import date

from padel_bot.monitoring import models
from padel_bot.monitoring.models import Subscription
from tests.conftest import dt

MON = date(2026, 9, 21)
NOW = dt("2026-09-15T12:00:00")  # Tuesday


def sub(**changes) -> Subscription:
    base = Subscription(
        id=1,
        chat_id=7,
        lang="ru",
        venue_key=None,
        day=MON,
        weekday=None,
        hour_from=16,
        hours=1,
        min_courts=1,
        changed_at=NOW,
    )
    return replace(base, **changes)


def test_toggle_length_cycles_and_ends_by_two():
    assert [models.toggle_length(sub(hours=h)).hours for h in (1, 2, 3)] == [2, 3, 1]
    assert [models.toggle_length(sub(hour_from=24, hours=h)).hours for h in (1, 2)] == [2, 1]
    assert models.toggle_length(sub(hour_from=25)) == sub(hour_from=25)


def test_toggle_club_and_courts(venues):
    keys = []
    current = sub()
    for _ in range(3):
        current = models.toggle_club(current, venues)
        keys.append(current.venue_key)
    assert keys == ["pp", "gp", None]
    assert models.toggle_club(sub(venue_key="removed"), venues).venue_key == "pp"
    assert models.toggle_courts(sub()).min_courts == 2
    assert models.toggle_courts(sub(min_courts=2)).min_courts == 1


def test_toggle_kind():
    weekly = models.toggle_kind(sub(), NOW)
    assert (weekly.day, weekly.weekday) == (None, 0)
    assert models.toggle_kind(weekly, NOW).day == MON
    # On Monday itself, too close to 16:00: next week.
    assert models.toggle_kind(weekly, dt("2026-09-21T15:40:00")).day == date(2026, 9, 28)
    assert models.toggle_kind(weekly, dt("2026-09-21T15:20:00")).day == MON
    # 03:00 on Monday is still Sunday's play day, so Monday is later today.
    assert models.toggle_kind(weekly, dt("2026-09-21T03:00:00")).day == MON
    # Monday 01:00 is the night after Monday: at 00:40 on Tuesday it's still coming.
    late = sub(day=None, weekday=0, hour_from=25)
    assert models.toggle_kind(late, dt("2026-09-22T00:20:00")).day == MON
    assert models.toggle_kind(late, dt("2026-09-22T00:40:00")).day == date(2026, 9, 28)
