from datetime import date

from padel_bot.reservio.service import AvailabilityService
from tests.conftest import FakeClient, dt, slot

DAY = date(2026, 9, 15)
NOW = dt("2026-09-15T09:00:00")


async def test_booking_links_prefer_checkout_and_fall_back(venues):
    client = FakeClient(
        {"pp1": [slot("2026-09-15T18:00:00")], "pp2": [slot("2026-09-15T18:00:00")]},
        checkout_failing={"pp2"},
    )
    svc = AvailabilityService(client, venues)
    result = await svc.get_availability(DAY, now=NOW)
    slots = sorted(result.slots, key=lambda s: s.court.name)

    links = await svc.booking_links(slots)

    assert links == [
        "https://pp.reservio.com/order?orderId=o-pp1&what=checkout",
        slots[1].booking_url,
    ]
