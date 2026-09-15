import logging
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from padel_bot.reservio.models import RawSlot

log = logging.getLogger(__name__)

PAGE_LIMIT = 100

ORDER_ITEMS = "order { id items { ... on AppointmentOrderItem { id time unavailabilityReason } } }"
ORDER_QUERY = (
    "query Order($input: bookingFrontByDomainQueryInput!, $orderInput: OrderInput!) "
    "{ bookingFrontByDomain(input: $input) { ... on Business { id "
    "order(orderInput: $orderInput) { id items { ... on AppointmentOrderItem { id } } } } } }"
)
SET_TIME_MUTATION = (
    "mutation SetTime($input: SetTimeToAppointmentOrderItemInput!) "
    "{ setTimeToAppointmentOrderItem(input: $input) { " + ORDER_ITEMS + " } }"
)


class ReservioError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        # Seconds Reservio asked to wait before the next request (HTTP 429), if it said so.
        self.retry_after = retry_after


class ReservioClient:
    """Thin async client for the public Reservio JSON:API (no auth needed)."""

    def __init__(self, base_url: str = "https://api.reservio.com", timeout: float = 15.0) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={
                "Accept": "application/vnd.api+json",
                "User-Agent": "padel-batumi-bot (+https://github.com/kairick/padel-bot)",
            },
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_slots(
        self, business_id: str, service_id: str, date_from: date, date_to: date
    ) -> list[RawSlot]:
        """Free slots of a service. Reservio filters by whole days, `date_to` is inclusive."""
        slots: list[RawSlot] = []
        offset = 0
        while True:
            params = {
                "filter[from]": date_from.isoformat(),
                "filter[to]": date_to.isoformat(),
                "filter[serviceId]": service_id,
                "ignoreBookingBoundaries": 0,
                "page[limit]": PAGE_LIMIT,
                "page[offset]": offset,
            }
            try:
                resp = await self._http.get(
                    f"/v2/businesses/{business_id}/availability/booking-slots", params=params
                )
                if resp.status_code == 429:
                    raise ReservioError(
                        f"booking-slots rate limited for service {service_id}",
                        retry_after=parse_retry_after(resp.headers.get("retry-after")),
                    )
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                raise ReservioError(f"booking-slots failed for service {service_id}: {e}") from e

            page = [parse_slot(item) for item in payload.get("data", [])]
            slots.extend(page)
            if not payload.get("links", {}).get("next") or len(page) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
        return slots

    async def create_checkout_url(
        self,
        subdomain: str,
        business_id: str,
        service_id: str,
        resource_id: str | None,
        start: datetime,
    ) -> str:
        """Create a draft order with court and time preselected, return a link to it.

        Mirrors what the booking page does: /booking?step=2 creates an order, then the
        time is set via GraphQL. A draft order does not hold the slot.

        The link opens the order's time step, where the user taps Continue. Linking straight
        to `what=checkout` shows a 404 on the first visit: for that step Reservio's server
        doesn't pass the order id to the page, which then only reads it from a cookie that
        isn't set yet. The time step gets the id from the server.
        """
        if not resource_id:
            raise ReservioError("checkout link needs a resource id")
        base = f"https://{subdomain}.reservio.com"
        graphql = f"{base}/api/graphql/booking-front"
        try:
            resp = await self._http.get(
                f"{base}/booking",
                params={"step": 2, "serviceId": service_id, "resourceId": resource_id},
                headers={"Accept": "text/html"},
                follow_redirects=False,
            )
            location = resp.headers.get("location", "")
            order_id = parse_qs(urlsplit(location).query).get("orderId", [""])[0]
            if not resp.is_redirect or not order_id:
                raise ReservioError(f"no order created (HTTP {resp.status_code})")

            data = await self._graphql(
                graphql,
                ORDER_QUERY,
                {"input": {"domain": subdomain}, "orderInput": {"orderId": order_id}},
            )
            item_id = data["bookingFrontByDomain"]["order"]["items"][0]["id"]

            data = await self._graphql(
                graphql,
                SET_TIME_MUTATION,
                {
                    "input": {
                        "appointmentOrderItemId": item_id,
                        "businessId": business_id,
                        "orderId": order_id,
                        "time": start.isoformat(),
                    }
                },
            )
            item = data["setTimeToAppointmentOrderItem"]["order"]["items"][0]
            if not item.get("time") or item.get("unavailabilityReason"):
                raise ReservioError(f"time not set: {item}")
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
            raise ReservioError(f"checkout link failed for service {service_id}: {e}") from e
        return f"{base}/order?orderId={order_id}&what=time"

    async def _graphql(self, url: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        resp = await self._http.post(
            url,
            json={"query": query, "variables": variables},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors") or not payload.get("data"):
            raise ReservioError(f"GraphQL error: {payload.get('errors')}")
        return payload["data"]


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Retry-After header in seconds: either a number of seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except TypeError, ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


def parse_slot(item: dict) -> RawSlot:
    attrs = item["attributes"]
    resource = (item.get("relationships", {}).get("resource") or {}).get("data") or {}
    return RawSlot(
        start=datetime.fromisoformat(attrs["start"]),
        end=datetime.fromisoformat(attrs["end"]),
        resource_id=resource.get("id"),
    )
