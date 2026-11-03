from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta

from padel_bot.domain import TZ, Lang, TimeRange, current_play_day
from padel_bot.reservio.models import CourtSlot, Venue

# Hours of a play day a subscription may start at: 07:00 ... 01:00 (25), ending by 02:00 (26).
FIRST_HOUR = 7
LAST_HOUR = 25
LAST_END_HOUR = 26
MAX_HOURS = 3
# A slot starting sooner than this can't be booked in time: never offered, never notified.
LEAD_TIME = timedelta(minutes=30)

type MatchKey = tuple[str, datetime]  # (venue key, slot start)
# A time in a notification: club, play day, slot start, free courts at that start.
type FreedTime = tuple[Venue, date, datetime, list[CourtSlot]]


def slot_start(day: date, hour: int) -> datetime:
    """Start of hour `hour` of play day `day` (25 means 01:00 of the next calendar day)."""
    return datetime.combine(day, time(0), TZ) + timedelta(hours=hour)


def nearest_day(weekday: int, hour: int, now: datetime) -> date:
    """Nearest play day with this weekday whose `hour` is still at least LEAD_TIME away."""
    today = current_play_day(now)
    day = today + timedelta(days=(weekday - today.weekday()) % 7)
    if slot_start(day, hour) - now < LEAD_TIME:
        day += timedelta(days=7)
    return day


@dataclass(frozen=True, slots=True)
class Subscription:
    id: int
    chat_id: int
    lang: Lang
    venue_key: str | None  # None means any club
    day: date | None  # exactly one of day and weekday is set
    weekday: int | None
    hour_from: int
    hours: int
    min_courts: int
    changed_at: datetime

    @property
    def time_range(self) -> TimeRange:
        return TimeRange(self.hour_from, self.hour_from + self.hours)

    def applies_to(self, play_day: date) -> bool:
        if self.day is not None:
            return play_day == self.day
        return play_day.weekday() == self.weekday

    def matches(self, start: datetime) -> bool:
        play_day = current_play_day(start)
        return self.applies_to(play_day) and self.time_range.contains(play_day, start)

    def watches_venue(self, venue_key: str) -> bool:
        return self.venue_key is None or self.venue_key == venue_key


@dataclass(frozen=True, slots=True)
class KnownMatch:
    notified_at: datetime | None
    gone_at: datetime | None


@dataclass(frozen=True, slots=True)
class ServiceState:
    venue_key: str
    last_ok_at: datetime  # start of the last cycle in which the whole club answered
    horizon: datetime  # latest slot start this service has ever returned


@dataclass(slots=True)
class SubscriptionPlan:
    subscription: Subscription
    reset_venues: set[str] = field(default_factory=set)  # forget all matches of these clubs
    insert: list[MatchKey] = field(default_factory=list)  # remember silently
    set_gone: list[MatchKey] = field(default_factory=list)
    clear_gone: list[MatchKey] = field(default_factory=list)
    send: list[MatchKey] = field(default_factory=list)  # written only after a successful send

    def is_empty(self) -> bool:
        return not (
            self.reset_venues or self.insert or self.set_gone or self.clear_gone or self.send
        )


@dataclass(slots=True)
class CyclePlan:
    ok_venues: set[str]
    service_states: dict[str, ServiceState]
    subscriptions: list[SubscriptionPlan]
    free: dict[MatchKey, list[CourtSlot]]  # free courts per match, for the notification


# Subscription card toggles (watch-ui buttons): pure, return the subscription unchanged when
# there's nothing to switch.


def toggle_kind(sub: Subscription, now: datetime) -> Subscription:
    if sub.day is not None:
        return replace(sub, day=None, weekday=sub.day.weekday())
    assert sub.weekday is not None
    return replace(sub, day=nearest_day(sub.weekday, sub.hour_from, now), weekday=None)


def toggle_length(sub: Subscription) -> Subscription:
    for step in range(1, MAX_HOURS):
        hours = (sub.hours - 1 + step) % MAX_HOURS + 1
        if sub.hour_from + hours <= LAST_END_HOUR:
            return replace(sub, hours=hours)
    return sub


def toggle_club(sub: Subscription, venues: list[Venue]) -> Subscription:
    keys: list[str | None] = [None, *(v.key for v in venues)]
    current = keys.index(sub.venue_key) if sub.venue_key in keys else 0
    return replace(sub, venue_key=keys[(current + 1) % len(keys)])


def toggle_courts(sub: Subscription) -> Subscription:
    return replace(sub, min_courts=2 if sub.min_courts == 1 else 1)
