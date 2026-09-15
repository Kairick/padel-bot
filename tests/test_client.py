import json
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
import respx

from padel_bot.reservio.client import ReservioClient, ReservioError, parse_retry_after

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


BOOKING = "https://pp.reservio.com/booking"
GRAPHQL = "https://pp.reservio.com/api/graphql/booking-front"
START = datetime.fromisoformat("2026-09-21T11:00:00+04:00")


def gql_order(item_id: str = "item-1") -> httpx.Response:
    order = {"id": "ord-1", "items": [{"id": item_id}]}
    return httpx.Response(
        200, json={"data": {"bookingFrontByDomain": {"id": "b1", "order": order}}}
    )


def gql_set_time(time: str | None) -> httpx.Response:
    item = {"id": "item-1", "time": time, "unavailabilityReason": None}
    order = {"id": "ord-1", "items": [item]}
    return httpx.Response(200, json={"data": {"setTimeToAppointmentOrderItem": {"order": order}}})


@respx.mock
async def test_create_checkout_url():
    booking = respx.get(BOOKING).mock(
        return_value=httpx.Response(
            307, headers={"location": "https://pp.reservio.com/order?orderId=ord-1&what=time"}
        )
    )
    gql = respx.post(GRAPHQL).mock(
        side_effect=[gql_order(), gql_set_time("2026-09-21T07:00:00+00:00")]
    )
    client = ReservioClient()
    url = await client.create_checkout_url("pp", "b1", "s1", "r1", START)
    await client.aclose()

    # Not what=checkout: Reservio renders a 404 there when the order cookie isn't set yet.
    assert url == "https://pp.reservio.com/order?orderId=ord-1&what=time"
    params = booking.calls.last.request.url.params
    assert (params["step"], params["serviceId"], params["resourceId"]) == ("2", "s1", "r1")
    set_time = json.loads(gql.calls[1].request.content)["variables"]["input"]
    assert set_time == {
        "appointmentOrderItemId": "item-1",
        "businessId": "b1",
        "orderId": "ord-1",
        "time": "2026-09-21T11:00:00+04:00",
    }


@respx.mock
async def test_create_checkout_url_fails_when_time_not_set():
    respx.get(BOOKING).mock(
        return_value=httpx.Response(307, headers={"location": "/order?orderId=ord-1&what=time"})
    )
    respx.post(GRAPHQL).mock(side_effect=[gql_order(), gql_set_time(None)])
    client = ReservioClient()
    with pytest.raises(ReservioError):
        await client.create_checkout_url("pp", "b1", "s1", "r1", START)
    await client.aclose()


@respx.mock
async def test_create_checkout_url_fails_without_redirect():
    respx.get(BOOKING).mock(return_value=httpx.Response(200, text="<html></html>"))
    client = ReservioClient()
    with pytest.raises(ReservioError):
        await client.create_checkout_url("pp", "b1", "s1", "r1", START)
    await client.aclose()


@respx.mock
async def test_rate_limit_passes_retry_after():
    respx.get(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "120"}))
    client = ReservioClient()
    with pytest.raises(ReservioError) as e:
        await client.get_slots("b1", "s1", date(2026, 9, 15), date(2026, 9, 15))
    await client.aclose()
    assert e.value.retry_after == 120


def test_parse_retry_after():
    now = datetime.fromisoformat("2026-09-15T10:00:00+00:00")
    assert parse_retry_after("30") == 30
    assert parse_retry_after("Tue, 15 Sep 2026 10:01:30 GMT", now=now) == 90
    assert parse_retry_after("Tue, 15 Sep 2026 09:00:00 GMT", now=now) == 0
    assert parse_retry_after("soon") is None
    assert parse_retry_after(None) is None


@respx.mock
async def test_http_error_raises_reservio_error():
    respx.get(URL).mock(return_value=httpx.Response(500))
    client = ReservioClient()
    with pytest.raises(ReservioError):
        await client.get_slots("b1", "s1", date(2026, 9, 15), date(2026, 9, 15))
    await client.aclose()
