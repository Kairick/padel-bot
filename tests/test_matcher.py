"""Scenarios of the "court got freed" rule, see PLAN_MONITORING.md."""

from datetime import date, datetime, timedelta

from padel_bot.monitoring.matcher import plan_cycle
from padel_bot.monitoring.models import (
    CyclePlan,
    KnownMatch,
    ServiceState,
    Subscription,
    SubscriptionPlan,
)
from padel_bot.reservio.client import ReservioError
from tests.conftest import dt, slot

NOW = dt("2026-09-15T12:00:00")
LAST_OK = dt("2026-09-15T11:50:00")
LONG_AGO = dt("2026-09-01T10:00:00")
MON = date(2026, 9, 21)
MON_16 = dt("2026-09-21T16:00:00")
FAR = "2026-09-22T12:00:00"
SERVICES = {"pp1": "pp", "pp2": "pp", "gpa-day": "gp", "gpa-eve": "gp"}


def subscription(
    id_: int = 1,
    *,
    day: date | None = MON,
    weekday: int | None = None,
    hour: int = 16,
    hours: int = 1,
    venue: str | None = None,
    courts: int = 1,
    changed: datetime = LONG_AGO,
) -> Subscription:
    return Subscription(
        id=id_,
        chat_id=7,
        lang="ru",
        venue_key=venue,
        day=None if weekday is not None else day,
        weekday=weekday,
        hour_from=hour,
        hours=hours,
        min_courts=courts,
        changed_at=changed,
    )


def states(
    horizon: str = FAR, last_ok: datetime = LAST_OK, horizons: dict[str, str] | None = None
) -> dict[str, ServiceState]:
    result = {sid: ServiceState(vk, last_ok, dt(horizon)) for sid, vk in SERVICES.items()}
    for sid, value in (horizons or {}).items():
        result[sid] = ServiceState(SERVICES[sid], last_ok, dt(value))
    return result


def run(venues, subs, data=None, *, known=None, st=None, now=NOW) -> CyclePlan:
    results = {sid: [] for sid in SERVICES} | (data or {})
    return plan_cycle(
        venues=venues,
        results=results,
        subscriptions=subs,
        known=known or {},
        states=states() if st is None else st,
        cycle_started_at=now,
        now=now,
    )


def for_sub(plan: CyclePlan, sub_id: int = 1) -> SubscriptionPlan | None:
    return next((p for p in plan.subscriptions if p.subscription.id == sub_id), None)


def known(*starts: datetime, gone_at: datetime | None = None, venue: str = "pp"):
    return {1: {(venue, s): KnownMatch(None, gone_at) for s in starts}}


def test_new_subscription_is_baselined_silently(venues):
    sub = subscription(changed=dt("2026-09-15T11:55:00"))
    plan = run(venues, [sub], {"pp1": [slot("2026-09-21T16:00:00")]})

    p = for_sub(plan)
    assert p is not None
    assert p.reset_venues == {"pp", "gp"}
    assert p.insert == [("pp", MON_16)]
    assert p.send == []


def test_subscription_changed_exactly_at_cycle_start_is_baselined(venues):
    plan = run(venues, [subscription(changed=LAST_OK)], {"pp1": [slot("2026-09-21T16:00:00")]})
    p = for_sub(plan)
    assert p is not None and p.send == [] and p.insert == [("pp", MON_16)]


def test_first_run_without_poll_state_is_silent(venues):
    plan = run(venues, [subscription()], {"pp1": [slot("2026-09-21T16:00:00")]}, st={})
    p = for_sub(plan)
    assert p is not None and p.send == [] and p.reset_venues == {"pp", "gp"}

    # A service added to venues.yaml later: only its club is baselined.
    partial = states()
    del partial["pp2"]
    plan = run(venues, [subscription()], {"pp1": [slot("2026-09-21T16:00:00")]}, st=partial)
    p = for_sub(plan)
    assert p is not None and p.send == [] and p.reset_venues == {"pp"}


def test_freed_slot_is_sent(venues):
    plan = run(venues, [subscription()], {"pp1": [slot("2026-09-21T16:00:00")]})

    p = for_sub(plan)
    assert p is not None
    assert p.send == [("pp", MON_16)]
    assert p.insert == [] and p.reset_venues == set()
    assert [s.court.name for s in plan.free[("pp", MON_16)]] == ["Padel 1"]


def test_slot_entering_the_window_is_silent(venues):
    # The service has never returned anything this late: the slot was beyond the window,
    # even if 16:00 is already less than "now + 7 days" by the calendar.
    st = states(horizons={"pp1": "2026-09-21T15:00:00"})
    plan = run(venues, [subscription()], {"pp1": [slot("2026-09-21T16:00:00")]}, st=st)

    p = for_sub(plan)
    assert p is not None and p.insert == [("pp", MON_16)] and p.send == []


def test_two_courts_one_long_free_other_freed(venues):
    data = {"pp1": [slot("2026-09-21T16:00:00")], "pp2": [slot("2026-09-21T16:00:00")]}

    plan = run(venues, [subscription(courts=2)], data, known=known())
    p = for_sub(plan)
    assert p is not None and p.send == [("pp", MON_16)]

    # The second court didn't get freed, it just entered the window: one real court is not two.
    st = states(horizons={"pp2": "2026-09-21T15:00:00"})
    plan = run(venues, [subscription(courts=2)], data, st=st)
    p = for_sub(plan)
    assert p is not None and p.send == [] and p.insert == [("pp", MON_16)]

    # For a one-court subscription the freed court alone is enough.
    plan = run(venues, [subscription(courts=1)], data, st=st)
    p = for_sub(plan)
    assert p is not None and p.send == [("pp", MON_16)]


def test_two_courts_need_two_free_courts_in_one_club(venues):
    data = {"pp1": [slot("2026-09-21T16:00:00")], "gpa-eve": [slot("2026-09-21T16:00:00")]}
    assert for_sub(run(venues, [subscription(courts=2)], data)) is None


def test_flapping_slot(venues):
    data = {"pp1": [slot("2026-09-21T16:00:00")]}

    back_soon = known(MON_16, gone_at=NOW - timedelta(minutes=10))
    p = for_sub(run(venues, [subscription()], data, known=back_soon))
    assert p is not None and p.clear_gone == [("pp", MON_16)] and p.send == []

    back_later = known(MON_16, gone_at=NOW - timedelta(minutes=40))
    p = for_sub(run(venues, [subscription()], data, known=back_later))
    assert p is not None and p.send == [("pp", MON_16)] and p.clear_gone == []


def test_known_match_that_disappears_gets_gone_mark(venues):
    p = for_sub(run(venues, [subscription()], known=known(MON_16)))
    assert p is not None and p.set_gone == [("pp", MON_16)]

    already_gone = known(MON_16, gone_at=NOW - timedelta(hours=1))
    assert for_sub(run(venues, [subscription()], known=already_gone)) is None

    # Still one free court is not enough for a two-court subscription.
    p = for_sub(
        run(
            venues,
            [subscription(courts=2)],
            {"pp1": [slot("2026-09-21T16:00:00")]},
            known=known(MON_16),
        )
    )
    assert p is not None and p.set_gone == [("pp", MON_16)]


def test_known_match_stays_quiet(venues):
    plan = run(
        venues, [subscription()], {"pp1": [slot("2026-09-21T16:00:00")]}, known=known(MON_16)
    )
    assert for_sub(plan) is None


def test_failed_service_skips_the_whole_club(venues):
    data = {
        "gpa-day": [slot("2026-09-21T16:00:00")],
        "gpa-eve": ReservioError("boom"),
        "pp1": [slot("2026-09-21T16:00:00")],
    }
    plan = run(venues, [subscription()], data, known=known(MON_16, venue="gp"))

    assert plan.ok_venues == {"pp"}
    assert set(plan.service_states) == {"pp1", "pp2"}
    p = for_sub(plan)
    assert p is not None
    assert p.send == [("pp", MON_16)]
    assert p.set_gone == []  # the gp match is not marked gone: gp didn't answer

    results = {"pp1": [], "pp2": [], "gpa-day": []}  # a service missing from results
    plan = plan_cycle(
        venues=venues,
        results=results,
        subscriptions=[],
        known={},
        states={},
        cycle_started_at=NOW,
        now=NOW,
    )
    assert plan.ok_venues == {"pp"}


def test_slot_after_midnight_belongs_to_previous_weekday(venues):
    sub = subscription(weekday=0, hour=25)  # every Monday, 01:00: the night after Monday
    data = {"pp1": [slot("2026-09-21T01:00:00"), slot("2026-09-22T01:00:00")]}

    p = for_sub(run(venues, [sub], data))

    assert p is not None
    assert p.send == [("pp", dt("2026-09-22T01:00:00"))]


def test_weekly_subscription_matches_every_such_day_in_the_window(venues):
    sub = subscription(weekday=1, hour=20)  # Tuesdays: today and next week
    data = {"pp1": [slot("2026-09-15T20:00:00"), slot("2026-09-22T20:00:00")]}
    st = states(horizon="2026-09-22T23:00:00")

    p = for_sub(run(venues, [sub], data, st=st))

    assert p is not None
    assert p.send == [("pp", dt("2026-09-15T20:00:00")), ("pp", dt("2026-09-22T20:00:00"))]


def test_slot_starting_too_soon_is_never_sent(venues):
    now = dt("2026-09-21T15:40:00")
    st = states(last_ok=now - timedelta(minutes=10))
    data = {"pp1": [slot("2026-09-21T16:00:00")]}

    p = for_sub(run(venues, [subscription()], data, st=st, now=now))
    assert p is not None and p.insert == [("pp", MON_16)] and p.send == []

    gone = known(MON_16, gone_at=now - timedelta(hours=1))
    p = for_sub(run(venues, [subscription()], data, known=gone, st=st, now=now))
    assert p is not None and p.clear_gone == [("pp", MON_16)] and p.send == []


def test_past_slots_are_ignored(venues):
    data = {"pp1": [slot("2026-09-15T11:00:00")]}
    sub = subscription(day=date(2026, 9, 15), hour=11)
    assert for_sub(run(venues, [sub], data)) is None
    assert for_sub(run(venues, [sub], known=known(dt("2026-09-15T11:00:00")))) is None


def test_night_break(venues):
    morning = dt("2026-09-15T07:50:00")
    st = states(horizon="2026-09-21T23:00:00", last_ok=dt("2026-09-14T23:40:00"))
    subs = [subscription(1), subscription(2, day=date(2026, 9, 22), hour=7)]
    data = {"pp1": [slot("2026-09-21T16:00:00")], "pp2": [slot("2026-09-22T07:00:00")]}

    plan = run(venues, subs, data, st=st, now=morning)

    freed_at_night = for_sub(plan, 1)
    entered_at_night = for_sub(plan, 2)
    assert freed_at_night is not None and freed_at_night.send == [("pp", MON_16)]
    assert entered_at_night is not None and entered_at_night.send == []
    assert entered_at_night.insert == [("pp", dt("2026-09-22T07:00:00"))]


def test_horizon_only_grows(venues):
    st = states(horizons={"pp1": "2026-09-23T10:00:00"})
    del st["gpa-day"]
    data = {"pp1": [slot("2026-09-21T16:00:00")], "pp2": [slot("2026-09-22T20:00:00")]}

    plan = run(venues, [], data, st=st)

    got = {sid: s.horizon for sid, s in plan.service_states.items()}
    assert got == {
        "pp1": dt("2026-09-23T10:00:00"),  # the response didn't reach the old horizon
        "pp2": dt("2026-09-22T20:00:00"),
        "gpa-day": NOW,  # nothing seen yet
        "gpa-eve": dt(FAR),
    }
    assert {s.last_ok_at for s in plan.service_states.values()} == {NOW}


def test_court_with_several_services_counts_once(venues):
    data = {"gpa-day": [slot("2026-09-21T16:00:00")], "gpa-eve": [slot("2026-09-21T16:00:00")]}
    st = states(horizons={"gpa-day": "2026-09-21T15:00:00"})

    plan = run(venues, [subscription(venue="gp")], data, st=st)

    p = for_sub(plan)
    assert p is not None and p.send == [("gp", MON_16)]
    assert [s.court.name for s in plan.free[("gp", MON_16)]] == ["Court A"]
    assert for_sub(run(venues, [subscription(venue="gp", courts=2)], data, st=st)) is None


def test_subscription_to_one_club_ignores_the_other(venues):
    plan = run(venues, [subscription(venue="gp")], {"pp1": [slot("2026-09-21T16:00:00")]})
    assert for_sub(plan) is None


def test_hour_range(venues):
    sub = subscription(hour=16, hours=2)
    data = {
        "pp1": [
            slot("2026-09-21T15:30:00"),
            slot("2026-09-21T16:00:00"),
            slot("2026-09-21T17:30:00"),
            slot("2026-09-21T18:00:00"),
        ]
    }
    p = for_sub(run(venues, [sub], data))
    assert p is not None
    assert p.send == [("pp", MON_16), ("pp", dt("2026-09-21T17:30:00"))]
