import asyncio
from datetime import date

from padel_bot.reservio.service import AvailabilityService, TimeRange, current_play_day
from tests.conftest import FakeClient, dt, slot

DAY = date(2026, 9, 15)
NOW = dt("2026-09-15T09:00:00")


async def test_play_day_window_and_past_slots(venues):
    client = FakeClient(
        {
            "pp1": [
                slot("2026-09-15T00:00:00"),  # night of previous play day
                slot("2026-09-15T08:00:00"),  # already in the past
                slot("2026-09-15T18:00:00"),
                slot("2026-09-16T01:00:00"),  # after midnight, same play day
                slot("2026-09-16T10:00:00"),  # next play day
            ]
        }
    )
    svc = AvailabilityService(client, venues)
    result = await svc.get_availability(DAY, now=NOW)
    assert [s.start.isoformat() for s in result.slots] == [
        "2026-09-15T18:00:00+04:00",
        "2026-09-16T01:00:00+04:00",
    ]
    assert client.calls[0][1:] == (DAY, date(2026, 9, 16))


async def test_time_range_filter(venues):
    client = FakeClient({"pp1": [slot("2026-09-15T12:00:00"), slot("2026-09-15T19:00:00")]})
    svc = AvailabilityService(client, venues)
    result = await svc.get_availability(DAY, TimeRange(17, 30), now=NOW)
    assert [s.start.hour for s in result.slots] == [19]


async def test_multi_service_court_uses_service_price(venues):
    client = FakeClient(
        {"gpa-day": [slot("2026-09-15T14:00:00")], "gpa-eve": [slot("2026-09-15T20:00:00")]}
    )
    svc = AvailabilityService(client, venues)
    result = await svc.get_availability(DAY, now=NOW)
    assert [(s.court.name, s.start.hour, int(s.price)) for s in result.slots] == [
        ("Court A", 14, 65),
        ("Court A", 20, 80),
    ]
    assert (
        result.slots[0].booking_url
        == "https://gp.reservio.com/booking?step=2&serviceId=gpa-day&resourceId=r1"
    )


async def test_failed_venue_is_reported(venues):
    client = FakeClient({"pp1": [slot("2026-09-15T18:00:00")]}, failing={"gpa-day"})
    svc = AvailabilityService(client, venues)
    result = await svc.get_availability(DAY, now=NOW)
    assert [v.key for v in result.failed_venues] == ["gp"]
    assert len(result.slots) == 1


async def test_cache_and_inflight_dedup(venues):
    client = FakeClient({})
    svc = AvailabilityService(client, venues, ttl_seconds=60)
    await asyncio.gather(*(svc.get_availability(DAY, now=NOW) for _ in range(5)))
    assert len(client.calls) == 4  # one per service
    await svc.get_availability(DAY, now=NOW)
    assert len(client.calls) == 4  # served from cache
    await svc.get_availability(DAY, now=NOW, force_refresh=True)
    assert len(client.calls) == 8


def test_current_play_day():
    assert current_play_day(dt("2026-09-15T03:00:00")) == date(2026, 9, 14)
    assert current_play_day(dt("2026-09-15T07:00:00")) == date(2026, 9, 15)
