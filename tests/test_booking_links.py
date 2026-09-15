import asyncio
from dataclasses import replace
from datetime import date

from padel_bot.reservio.service import AvailabilityService
from tests.conftest import FakeClient, dt, slot

DAY = date(2026, 9, 15)
NOW = dt("2026-09-15T09:00:00")


async def make(venues, **client_kwargs):
    client = FakeClient(
        {"pp1": [slot("2026-09-15T18:00:00")], "pp2": [slot("2026-09-15T18:00:00")]},
        **client_kwargs,
    )
    svc = AvailabilityService(client, venues)
    result = await svc.get_availability(DAY, now=NOW)
    return client, svc, sorted(result.slots, key=lambda s: s.court.name)


async def test_prefers_checkout_and_falls_back_on_error(venues):
    client, svc, slots = await make(venues, checkout_failing={"pp2"})

    links = await svc.booking_links(slots, user_id=1)

    assert links[0].startswith("https://pp.reservio.com/order?orderId=o-pp1-")
    assert links[1] == slots[1].booking_url


async def test_links_are_cached_per_user(venues):
    client, svc, slots = await make(venues)

    first = await svc.booking_links(slots, user_id=1)
    again = await svc.booking_links(slots, user_id=1)
    other_user = await svc.booking_links(slots, user_id=2)

    assert again == first
    assert len(client.checkout_calls) == 4  # two courts for user 1, two for user 2
    assert set(other_user).isdisjoint(first)  # never share a draft order between people


async def test_failed_links_are_not_cached(venues):
    client, svc, slots = await make(venues, checkout_failing={"pp2"})

    await svc.booking_links(slots, user_id=1)
    await svc.booking_links(slots, user_id=1)

    assert client.checkout_calls.count("pp1") == 1
    assert client.checkout_calls.count("pp2") == 2


async def test_concurrent_taps_share_one_draft(venues):
    client, svc, slots = await make(venues)
    client.checkout_delay = 0.05

    results = await asyncio.gather(*(svc.booking_links(slots, user_id=1) for _ in range(5)))

    assert len(client.checkout_calls) == 2
    assert all(r == results[0] for r in results)


async def test_links_are_cached_per_venue(venues):
    client, svc, slots = await make(venues)
    base = slots[0]
    # Same service, resource and time in two different clubs must never share a draft.
    in_other_venue = replace(base, venue=venues[1], court=venues[1].courts[0])

    first = await svc.booking_links([base], user_id=1)
    second = await svc.booking_links([in_other_venue], user_id=1)

    assert len(client.checkout_calls) == 2
    assert first[0].startswith("https://pp.reservio.com/")
    assert second[0].startswith("https://gp.reservio.com/")


async def test_slow_links_fall_back_after_timeout(venues):
    client, svc, slots = await make(venues)
    client.checkout_delay = 1.0

    links = await svc.booking_links(slots, user_id=1, wait_seconds=0.05)

    assert links == [s.booking_url for s in slots]
