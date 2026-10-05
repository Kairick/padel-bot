"""Availability across all venues: parallel fetching, TTL cache, request de-duplication."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from cachetools import TTLCache

from padel_bot.domain import TZ, WHOLE_DAY, TimeRange
from padel_bot.reservio.client import ReservioClient
from padel_bot.reservio.models import CourtConfig, CourtSlot, RawSlot, ServiceConfig, Venue

log = logging.getLogger(__name__)

type CacheKey = tuple[str, str, date]
# (telegram user id, business id, service id, resource id, slot start)
type LinkKey = tuple[int, str, str, str | None, datetime]

LINK_TTL_SECONDS = 600
LINKS_TIMEOUT_SECONDS = 10.0


@dataclass(slots=True)
class Availability:
    day: date
    slots: list[CourtSlot]
    failed_venues: list[Venue] = field(default_factory=list)

    def by_venue(self) -> dict[str, list[CourtSlot]]:
        result: dict[str, list[CourtSlot]] = {}
        for s in self.slots:
            result.setdefault(s.venue.key, []).append(s)
        return result


class AvailabilityService:
    def __init__(self, client: ReservioClient, venues: list[Venue], ttl_seconds: int = 60) -> None:
        self._client = client
        self.venues = venues
        self._cache: TTLCache[CacheKey, list[RawSlot]] = TTLCache(maxsize=2048, ttl=ttl_seconds)
        self._inflight: dict[CacheKey, asyncio.Task[list[RawSlot]]] = {}
        self._links: TTLCache[LinkKey, str] = TTLCache(maxsize=4096, ttl=LINK_TTL_SECONDS)
        self._links_inflight: dict[LinkKey, asyncio.Task[str]] = {}

    async def get_availability(
        self,
        day: date,
        time_range: TimeRange = WHOLE_DAY,
        *,
        force_refresh: bool = False,
        now: datetime | None = None,
    ) -> Availability:
        now = now or datetime.now(TZ)
        jobs = [
            (venue, court, service)
            for venue in self.venues
            for court in venue.courts
            for service in court.services
        ]
        results = await asyncio.gather(
            *(
                self._get_raw(venue.business_id, service.id, day, force_refresh)
                for venue, _, service in jobs
            ),
            return_exceptions=True,
        )

        slots: list[CourtSlot] = []
        failed: dict[str, Venue] = {}
        for (venue, court, service), result in zip(jobs, results, strict=True):
            if isinstance(result, BaseException):
                log.warning("fetch failed: %s", result)
                failed[venue.key] = venue
                continue
            for raw in result:
                start = raw.start.astimezone(TZ)
                if start <= now or not time_range.contains(day, start):
                    continue
                slots.append(court_slot(venue, court, service, raw))

        slots = dedupe(slots)
        slots.sort(key=lambda s: (s.start, s.venue.key, s.court.name))
        return Availability(day=day, slots=slots, failed_venues=list(failed.values()))

    async def booking_links(
        self, slots: list[CourtSlot], user_id: int, wait_seconds: float = LINKS_TIMEOUT_SECONDS
    ) -> list[str]:
        """Checkout links with time preselected, one per slot, in the same order.

        Each link is a Reservio draft order, so links are cached per user for a while and
        concurrent identical requests share one draft. Links are never shared between users:
        two people must not end up in the same order. Slots whose link fails or isn't ready
        within `wait_seconds` fall back to the plain court booking page; slow drafts keep
        running in the background and land in the cache for the next tap.
        """
        futures = [self._checkout_future(user_id, s) for s in slots]
        if futures:
            await asyncio.wait(futures, timeout=wait_seconds)
        links: list[str] = []
        for s, future in zip(slots, futures, strict=True):
            if not future.done():
                log.warning("checkout link timed out, using booking page")
                links.append(s.booking_url)
            elif future.cancelled() or future.exception() is not None:
                links.append(s.booking_url)  # the failure itself is logged by the task callback
            else:
                links.append(future.result())
        return links

    def _checkout_future(self, user_id: int, slot: CourtSlot) -> asyncio.Future[str]:
        key: LinkKey = (
            user_id,
            slot.venue.business_id,
            slot.service_id,
            slot.resource_id,
            slot.start,
        )
        if (cached := self._links.get(key)) is not None:
            future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            future.set_result(cached)
            return future
        if (task := self._links_inflight.get(key)) is None:
            task = asyncio.create_task(self._create_link(key, slot))
            self._links_inflight[key] = task

            def done(finished: asyncio.Task[str]) -> None:
                self._links_inflight.pop(key, None)
                # Also marks the exception as retrieved when nobody awaits it after a timeout.
                if not finished.cancelled() and (error := finished.exception()) is not None:
                    log.warning("checkout link failed: %r", error)

            task.add_done_callback(done)
        return task

    async def _create_link(self, key: LinkKey, slot: CourtSlot) -> str:
        url = await self._client.create_checkout_url(
            slot.venue.subdomain,
            slot.venue.business_id,
            slot.service_id,
            slot.resource_id,
            slot.start,
        )
        self._links[key] = url
        return url

    async def _get_raw(
        self, business_id: str, service_id: str, day: date, force_refresh: bool
    ) -> list[RawSlot]:
        key: CacheKey = (business_id, service_id, day)
        if not force_refresh and key in self._cache:
            return self._cache[key]
        if (task := self._inflight.get(key)) is None:
            task = asyncio.create_task(self._fetch(key))
            self._inflight[key] = task
            task.add_done_callback(lambda _: self._inflight.pop(key, None))
        return await asyncio.shield(task)

    async def _fetch(self, key: CacheKey) -> list[RawSlot]:
        business_id, service_id, day = key
        # Play day spills over midnight, so ask for the next calendar day too.
        raw = await self._client.get_slots(business_id, service_id, day, day + timedelta(days=1))
        self._cache[key] = raw
        return raw


def court_slot(venue: Venue, court: CourtConfig, service: ServiceConfig, raw: RawSlot) -> CourtSlot:
    return CourtSlot(
        venue=venue,
        court=court,
        service_id=service.id,
        resource_id=raw.resource_id,
        start=raw.start.astimezone(TZ),
        end=raw.end.astimezone(TZ),
        price=service.price,
    )


def dedupe(slots: list[CourtSlot]) -> list[CourtSlot]:
    seen: set[tuple[str, str, datetime]] = set()
    unique = []
    for s in slots:
        k = (s.venue.key, s.court.name, s.start)
        if k not in seen:
            seen.add(k)
            unique.append(s)
    return unique
