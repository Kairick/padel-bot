import logging
from datetime import date, datetime

import httpx

from padel_bot.reservio.models import RawSlot

log = logging.getLogger(__name__)

PAGE_LIMIT = 100


class ReservioError(Exception):
    pass


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


def parse_slot(item: dict) -> RawSlot:
    attrs = item["attributes"]
    resource = (item.get("relationships", {}).get("resource") or {}).get("data") or {}
    return RawSlot(
        start=datetime.fromisoformat(attrs["start"]),
        end=datetime.fromisoformat(attrs["end"]),
        resource_id=resource.get("id"),
    )
