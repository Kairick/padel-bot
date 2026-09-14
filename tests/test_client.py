import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from padel_bot.reservio.client import ReservioClient, ReservioError

FIXTURE = json.loads((Path(__file__).parent / "fixtures/booking_slots_padel_port.json").read_text())
URL = "https://api.reservio.com/v2/businesses/b1/availability/booking-slots"


@respx.mock
async def test_parses_real_response():
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    client = ReservioClient()
    slots = await client.get_slots("b1", "s1", date(2026, 9, 15), date(2026, 9, 16))
    await client.aclose()

    assert len(slots) == FIXTURE["meta"]["total"]
    first = slots[0]
    assert first.start.isoformat() == "2026-09-15T00:00:00+04:00"
    assert first.resource_id == "929c2389-5a21-444f-bb78-bdcaef2dbf3c"
    params = route.calls.last.request.url.params
    assert params["filter[from]"] == "2026-09-15"
    assert params["filter[to]"] == "2026-09-16"
    assert params["filter[serviceId]"] == "s1"


@respx.mock
async def test_follows_pagination(monkeypatch):
    monkeypatch.setattr("padel_bot.reservio.client.PAGE_LIMIT", 1)
    item = FIXTURE["data"][0]
    respx.get(URL, params={"page[offset]": "0"}).mock(
        return_value=httpx.Response(200, json={"data": [item], "links": {"next": "x"}})
    )
    respx.get(URL, params={"page[offset]": "1"}).mock(
        return_value=httpx.Response(200, json={"data": [], "links": {"next": None}})
    )
    client = ReservioClient()
    slots = await client.get_slots("b1", "s1", date(2026, 9, 15), date(2026, 9, 15))
    await client.aclose()
    assert len(slots) == 1


@respx.mock
async def test_http_error_raises_reservio_error():
    respx.get(URL).mock(return_value=httpx.Response(500))
    client = ReservioClient()
    with pytest.raises(ReservioError):
        await client.get_slots("b1", "s1", date(2026, 9, 15), date(2026, 9, 15))
    await client.aclose()
