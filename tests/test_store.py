import sqlite3
from dataclasses import replace
from datetime import date, timedelta

import pytest

from padel_bot.db import connect
from padel_bot.monitoring.matcher import CyclePlan, SubscriptionPlan
from padel_bot.monitoring.models import KnownMatch, ServiceState
from padel_bot.monitoring.store import (
    MAX_SUBSCRIPTIONS,
    DuplicateSubscriptionError,
    SubscriptionLimitError,
    SubscriptionStore,
)
from tests.conftest import dt

NOW = dt("2026-09-15T12:00:00")
MON = date(2026, 9, 21)
START = dt("2026-09-21T16:00:00")
LATER = dt("2026-09-21T17:00:00")


@pytest.fixture
def store(tmp_path):
    db = connect(tmp_path / "bot.sqlite3")
    yield SubscriptionStore(db)
    db.close()


def cycle(*plans: SubscriptionPlan, states: dict[str, ServiceState] | None = None) -> CyclePlan:
    return CyclePlan(
        ok_venues={"pp"}, service_states=states or {}, subscriptions=list(plans), free={}
    )


def test_create_get_list(store):
    sub = store.create(chat_id=1, lang="ru", day=MON, hour_from=16, now=NOW)

    assert store.get(sub.id) == sub
    assert store.list_for_chat(1, NOW) == [sub]
    assert store.list_for_chat(2, NOW) == []
    assert store.has_subscriptions()
    assert (sub.venue_key, sub.hours, sub.min_courts, sub.weekday) == (None, 1, 1, None)


def test_duplicate_and_limit(store):
    first = store.create(chat_id=1, lang="ru", day=MON, hour_from=16, now=NOW)
    with pytest.raises(DuplicateSubscriptionError) as e:
        store.create(chat_id=1, lang="en", day=MON, hour_from=16, now=NOW)
    assert e.value.existing_id == first.id

    for hour in range(17, 16 + MAX_SUBSCRIPTIONS):
        store.create(chat_id=1, lang="ru", day=MON, hour_from=hour, now=NOW)
    with pytest.raises(SubscriptionLimitError):
        store.create(chat_id=1, lang="ru", day=MON, hour_from=22, now=NOW)
    # An existing subscription still opens at the limit.
    with pytest.raises(DuplicateSubscriptionError):
        store.create(chat_id=1, lang="ru", day=MON, hour_from=16, now=NOW)
    # Weekly and dated subscriptions on the same hour are different ones.
    assert store.count_for_chat(1) == MAX_SUBSCRIPTIONS
    store.create(chat_id=2, lang="ru", weekday=0, hour_from=16, now=NOW)


def test_expired_date_subscriptions_leave_without_the_poller(store):
    # The poller doesn't run at night or with MONITOR_ENABLED=false.
    for hour in range(16, 16 + MAX_SUBSCRIPTIONS):
        store.create(chat_id=1, lang="ru", day=MON, hour_from=hour, now=NOW)
    assert len(store.list_for_chat(1, dt("2026-09-22T05:59:00"))) == MAX_SUBSCRIPTIONS

    morning = dt("2026-09-22T06:30:00")
    new = store.create(chat_id=1, lang="ru", day=date(2026, 9, 23), hour_from=16, now=morning)

    assert store.list_for_chat(1, morning) == [new]


def test_update_sets_changed_at_and_rejects_copies(store):
    store.create(chat_id=1, lang="ru", day=MON, hour_from=16, now=NOW)
    other = store.create(chat_id=1, lang="ru", day=MON, hour_from=17, now=NOW)
    later = NOW + timedelta(minutes=1)

    updated = store.update(replace(other, hour_from=18), later)

    assert updated.changed_at == later
    assert store.get(other.id) == updated
    with pytest.raises(DuplicateSubscriptionError):
        store.update(replace(updated, hour_from=16), later + timedelta(minutes=1))
    assert store.get(other.id) == updated


def test_schema_rejects_invalid_subscriptions(store):
    with pytest.raises(sqlite3.IntegrityError):
        store.create(chat_id=1, lang="ru", day=MON, hour_from=25, hours=2, now=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        store.create(chat_id=1, lang="ru", day=MON, weekday=0, hour_from=16, now=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        store.create(chat_id=1, lang="ru", hour_from=16, now=NOW)
    assert not store.has_subscriptions()


def test_set_lang_keeps_changed_at(store):
    sub = store.create(chat_id=1, lang="ru", day=MON, hour_from=16, now=NOW)

    store.set_lang(1, "en")

    stored = store.get(sub.id)
    assert stored is not None
    assert stored.lang == "en"
    assert stored.changed_at == sub.changed_at
    assert store.is_unchanged(sub)


def test_delete_checks_owner_and_cascades(store):
    sub = store.create(chat_id=1, lang="ru", day=MON, hour_from=16, now=NOW)
    store.mark_notified([(sub, [("pp", START)])], NOW)
    assert store.known_matches() == {sub.id: {("pp", START): KnownMatch(NOW, None)}}

    assert not store.delete(sub.id, chat_id=2)
    assert store.delete(sub.id, chat_id=1)

    assert store.known_matches() == {}
    assert not store.is_unchanged(sub)


def test_apply_cycle_skips_subscription_changed_during_the_cycle(store):
    sub = store.create(chat_id=1, lang="ru", day=MON, hour_from=16, now=NOW)
    changed = store.update(replace(sub, hours=2), NOW + timedelta(minutes=1))
    state = {"pp1": ServiceState("pp", NOW, LATER)}

    store.apply_cycle(
        cycle(SubscriptionPlan(sub, reset_venues={"pp"}, insert=[("pp", START)]), states=state),
        NOW,
    )

    assert store.known_matches() == {}
    assert store.poll_state() == state  # polling state is written regardless

    store.apply_cycle(cycle(SubscriptionPlan(changed, insert=[("pp", START)])), NOW)
    assert store.known_matches() == {changed.id: {("pp", START): KnownMatch(None, None)}}


def test_apply_cycle_gone_marks_and_reset(store):
    sub = store.create(chat_id=1, lang="ru", day=MON, hour_from=16, hours=2, now=NOW)
    store.apply_cycle(cycle(SubscriptionPlan(sub, insert=[("pp", START), ("pp", LATER)])), NOW)

    store.apply_cycle(cycle(SubscriptionPlan(sub, set_gone=[("pp", START)])), NOW)
    assert store.known_matches()[sub.id][("pp", START)] == KnownMatch(None, NOW)

    store.apply_cycle(cycle(SubscriptionPlan(sub, clear_gone=[("pp", START)])), NOW)
    assert store.known_matches()[sub.id][("pp", START)] == KnownMatch(None, None)

    store.apply_cycle(
        cycle(SubscriptionPlan(sub, reset_venues={"pp"}, insert=[("pp", LATER)])), NOW
    )
    assert store.known_matches() == {sub.id: {("pp", LATER): KnownMatch(None, None)}}


def test_mark_notified_clears_gone_and_skips_deleted(store):
    sub = store.create(chat_id=1, lang="ru", day=MON, hour_from=16, now=NOW)
    store.apply_cycle(cycle(SubscriptionPlan(sub, insert=[("pp", START)])), NOW)
    store.apply_cycle(cycle(SubscriptionPlan(sub, set_gone=[("pp", START)])), NOW)

    store.mark_notified([(sub, [("pp", START)])], LATER)
    assert store.known_matches()[sub.id][("pp", START)] == KnownMatch(LATER, None)

    store.delete(sub.id, chat_id=1)
    store.mark_notified([(sub, [("pp", START)])], LATER)  # no foreign key error
    assert store.known_matches() == {}


def test_delete_chat(store):
    for hour in (16, 17):
        store.create(chat_id=1, lang="ru", day=MON, hour_from=hour, now=NOW)
    store.create(chat_id=2, lang="ru", day=MON, hour_from=16, now=NOW)

    assert store.delete_chat(1) == 2
    assert [s.chat_id for s in store.all()] == [2]


def test_cleanup(store):
    night = dt("2026-09-22T05:00:00")  # still play day 21 September
    yesterday = store.create(chat_id=1, lang="ru", day=date(2026, 9, 20), hour_from=20, now=NOW)
    today = store.create(chat_id=1, lang="ru", day=MON, hour_from=23, now=NOW)
    weekly = store.create(chat_id=1, lang="ru", weekday=0, hour_from=16, hours=3, now=NOW)
    removed_club = store.create(
        chat_id=1, lang="ru", weekday=1, hour_from=16, venue_key="old", now=NOW
    )
    past, future = dt("2026-09-22T04:00:00"), dt("2026-09-28T17:00:00")
    store.apply_cycle(
        cycle(
            SubscriptionPlan(weekly, insert=[("pp", past), ("pp", future)]),
            states={
                "pp1": ServiceState("pp", NOW, future),
                "gone-service": ServiceState("pp", NOW, future),
            },
        ),
        NOW,
    )

    store.cleanup(night, venue_keys={"pp", "gp"}, service_ids={"pp1", "pp2"})

    assert {s.id for s in store.all()} == {today.id, weekly.id}
    assert yesterday.id not in store.known_matches()
    assert removed_club.id not in {s.id for s in store.all()}
    assert store.known_matches() == {weekly.id: {("pp", future): KnownMatch(None, None)}}
    assert set(store.poll_state()) == {"pp1"}

    store.cleanup(dt("2026-09-22T06:00:00"), venue_keys={"pp", "gp"}, service_ids={"pp1"})
    assert [s.id for s in store.all()] == [weekly.id]
