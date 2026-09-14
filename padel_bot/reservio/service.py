"""Availability across all venues: parallel fetching, TTL cache, request de-duplication."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from cachetools import TTLCache

from padel_bot.config import TZ
from padel_bot.reservio.client import ReservioClient, ReservioError
from padel_bot.reservio.models import CourtSlot, RawSlot, Venue

log = logging.getLogger(__name__)

# Clubs are open past midnight; a "play day" D covers [D 06:00, D+1 06:00).
DAY_START = time(6, 0)

type CacheKey = tuple[str, str, date]


@dataclass(frozen=True, slots=True)
class TimeRange:
    """Hours of a play day, e.g. 17..30 means 17:00 to 06:00 next day."""

    start_hour: int
    end_hour: int

    def contains(self, day: date, moment: datetime) -> bool:
        base = datetime.combine(day, time(0), TZ)
        start = base + timedelta(hours=self.start_hour)
        end = base + timedelta(hours=self.end_hour)
        return start <= moment < end


WHOLE_DAY = TimeRange(DAY_START.hour, DAY_START.hour + 24)


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
                slots.append(
                    CourtSlot(
                        venue=venue,
                        court=court,
                        service_id=service.id,
                        resource_id=raw.resource_id,
                        start=start,
                        end=raw.end.astimezone(TZ),
                        price=service.price,
                    )
                )

        slots = _dedupe(slots)
        slots.sort(key=lambda s: (s.start, s.venue.key, s.court.name))
        return Availability(day=day, slots=slots, failed_venues=list(failed.values()))

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


def _dedupe(slots: list[CourtSlot]) -> list[CourtSlot]:
    seen: set[tuple[str, str, datetime]] = set()
    unique = []
    for s in slots:
        k = (s.venue.key, s.court.name, s.start)
        if k not in seen:
            seen.add(k)
            unique.append(s)
    return unique


__all__ = [
    "WHOLE_DAY",
    "Availability",
    "AvailabilityService",
    "ReservioError",
    "TimeRange",
    "current_play_day",
]


def current_play_day(now: datetime | None = None) -> date:
    """Play day that is going on right now (before 06:00 it's still the previous day)."""
    now = (now or datetime.now(TZ)).astimezone(TZ)
    return (now - timedelta(hours=DAY_START.hour)).date()
