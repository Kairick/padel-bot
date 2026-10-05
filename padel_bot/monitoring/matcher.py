"""Decides which matches of a polling cycle to notify about and which to remember silently.

Pure functions: no I/O, no clock. The rule, in short:

- A match is a (club, slot start) with at least `min_courts` free courts that fits a
  subscription.
- Right after a subscription is created or changed, and before a club's first successful
  cycle, all current matches are remembered silently.
- A new match is notified only if enough of its courts were already inside the booking
  window last time (the service's horizon reached that start): then the slot was booked and
  got freed. Otherwise it has just entered the window and is remembered silently.
- A known match that disappeared gets `gone_at`. If it comes back within FLAP_TIME, it's
  noise; if later, it's a new release and is notified again.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from padel_bot.monitoring.models import (
    LEAD_TIME,
    CyclePlan,
    KnownMatch,
    MatchKey,
    ServiceState,
    Subscription,
    SubscriptionPlan,
)
from padel_bot.reservio.models import CourtSlot, RawSlot, Venue
from padel_bot.reservio.service import court_slot, dedupe

FLAP_TIME = timedelta(minutes=30)


def was_in_window(
    slot: CourtSlot,
    seen_by: Mapping[tuple[str, datetime], set[str]],
    states: Mapping[str, ServiceState],
) -> bool:
    """True if a service that returned this slot had already seen this far last time."""
    for service_id in seen_by[(slot.court.name, slot.start)]:
        old = states.get(service_id)
        if old is not None and old.horizon >= slot.start:
            return True
    return False


def plan_cycle(
    *,
    venues: Sequence[Venue],
    results: Mapping[str, Sequence[RawSlot] | BaseException],
    subscriptions: Sequence[Subscription],
    known: Mapping[int, Mapping[MatchKey, KnownMatch]],
    states: Mapping[str, ServiceState],
    cycle_started_at: datetime,
    now: datetime,
) -> CyclePlan:
    plans = {sub.id: SubscriptionPlan(sub) for sub in subscriptions}
    plan = CyclePlan(ok_venues=set(), service_states={}, subscriptions=[], free={})

    for venue in venues:
        services = [(court, service) for court in venue.courts for service in court.services]
        responses = {service.id: results.get(service.id) for _, service in services}
        if not all(isinstance(r, Sequence) for r in responses.values()):
            continue  # one court of a club may consist of several services: all or nothing
        plan.ok_venues.add(venue.key)

        old_states = [states.get(service.id) for _, service in services]
        last_ok_at = (
            min(s.last_ok_at for s in old_states if s is not None)
            if all(s is not None for s in old_states)
            else None
        )

        slots: list[CourtSlot] = []
        # Services that returned a court's slot: a court may have several (Grand Padel prices).
        seen_by: dict[tuple[str, datetime], set[str]] = {}
        for court, service in services:
            raw_slots = responses[service.id]
            assert isinstance(raw_slots, Sequence)
            for raw in raw_slots:
                slot = court_slot(venue, court, service, raw)
                seen_by.setdefault((court.name, slot.start), set()).add(service.id)
                if slot.start > now:
                    slots.append(slot)
            old = states.get(service.id)
            candidates = [s.start for s in raw_slots] + ([old.horizon] if old else [])
            horizon = max(candidates, default=cycle_started_at)
            plan.service_states[service.id] = ServiceState(venue.key, cycle_started_at, horizon)

        by_start: dict[datetime, list[CourtSlot]] = {}
        for slot in sorted(dedupe(slots), key=lambda s: (s.start, s.court.name)):
            by_start.setdefault(slot.start, []).append(slot)

        for sub in subscriptions:
            if not sub.watches_venue(venue.key):
                continue
            p = plans[sub.id]
            matches = {
                start
                for start, courts in by_start.items()
                if len(courts) >= sub.min_courts and sub.matches(start)
            }
            for start in matches:
                plan.free[(venue.key, start)] = by_start[start]

            if last_ok_at is None or sub.changed_at >= last_ok_at:
                p.reset_venues.add(venue.key)
                p.insert.extend((venue.key, start) for start in sorted(matches))
                continue

            venue_known = {k: m for k, m in known.get(sub.id, {}).items() if k[0] == venue.key}
            for start in sorted(matches):
                key = (venue.key, start)
                too_close = start - now < LEAD_TIME
                match = venue_known.get(key)
                if match is None:
                    in_window = sum(was_in_window(c, seen_by, states) for c in by_start[start])
                    freed = in_window >= sub.min_courts
                    (p.send if freed and not too_close else p.insert).append(key)
                elif match.gone_at is not None:
                    flapped = now - match.gone_at < FLAP_TIME
                    (p.clear_gone if flapped or too_close else p.send).append(key)
            for key, match in venue_known.items():
                if key[1] not in matches and key[1] > now and match.gone_at is None:
                    p.set_gone.append(key)

    plan.subscriptions = [p for p in plans.values() if not p.is_empty()]
    return plan
