import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from padel_bot.bot.keyboards import SlotCb
from padel_bot.db import connect
from padel_bot.monitoring.matcher import CyclePlan
from padel_bot.monitoring.poller import CycleOutcome, Poller, next_delay, quiet_seconds
from padel_bot.monitoring.store import SubscriptionStore
from padel_bot.reservio.client import ReservioError
from padel_bot.reservio.service import court_slot
from tests.conftest import FakeClient, dt, slot

T0 = dt("2026-09-15T12:00:00")
MON = date(2026, 9, 21)
STEP = timedelta(minutes=10)


class FakeBot:
    def __init__(self, errors: list[Exception] | None = None) -> None:
        self.errors = errors or []
        self.sent: list[tuple[int, str, object]] = []
        self.on_send = None  # called while the message is being sent

    async def send_message(self, chat_id: int, text: str, reply_markup=None) -> None:
        if self.errors:
            raise self.errors.pop(0)
        if self.on_send is not None:
            self.on_send()
        self.sent.append((chat_id, text, reply_markup))


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def store(tmp_path):
    db = connect(tmp_path / "bot.sqlite3")
    yield SubscriptionStore(db)
    db.close()


def make_poller(venues, store, bot=None, client=None, clock=None, sleeps=None):
    sleeps = sleeps if sleeps is not None else []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return Poller(
        bot or FakeBot(),
        client or FakeClient({}),
        venues,
        store,
        clock=clock or Clock(T0),
        sleep=sleep,
    )


async def freed_slot_setup(venues, store, bot, sleeps=None):
    """First cycle remembers the evening, then Padel 1 at 16:00 gets freed."""
    clock = Clock(T0)
    client = FakeClient({"pp1": [slot("2026-09-21T20:00:00")]})
    poller = make_poller(venues, store, bot, client, clock, sleeps)
    outcome = await poller.run_cycle()
    assert outcome == CycleOutcome(ok=True, notified_chats=0)
    assert bot.sent == []
    client.data["pp1"] = [slot("2026-09-21T16:00:00"), slot("2026-09-21T20:00:00")]
    clock.now += STEP
    return poller, clock, client


def test_quiet_seconds():
    assert quiet_seconds(dt("2026-09-15T12:00:00")) == 0
    assert quiet_seconds(dt("2026-09-15T07:50:00")) == 0
    assert quiet_seconds(dt("2026-09-15T23:49:00")) == 0
    assert quiet_seconds(dt("2026-09-15T03:00:00")) == 4 * 3600 + 50 * 60
    assert quiet_seconds(dt("2026-09-15T23:58:00")) == 7 * 3600 + 52 * 60
    # Computed in Batumi time whatever the timezone of the clock.
    utc_night = datetime.fromisoformat("2026-09-14T23:00:00+00:00")  # 03:00 in Batumi
    assert quiet_seconds(utc_night) == 4 * 3600 + 50 * 60


def test_next_delay():
    assert next_delay(600, 0, None) == 600
    assert next_delay(600, 1, None) == 1200
    assert next_delay(600, 3, None) == 3600
    assert next_delay(600, 50, None) == 3600
    assert next_delay(600, 0, 120) == 600
    assert next_delay(600, 1, 5000) == 5000


async def test_first_cycle_is_silent_then_freed_slot_is_notified(venues, store):
    store.create(chat_id=7, lang="ru", day=MON, hour_from=16, now=T0 - timedelta(hours=1))
    bot = FakeBot()
    poller, clock, client = await freed_slot_setup(venues, store, bot)
    assert {call[1:] for call in client.calls} == {(date(2026, 9, 15), date(2026, 9, 23))}
    assert len(client.calls) == 4  # one request per service

    outcome = await poller.run_cycle()

    assert outcome.notified_chats == 1
    chat_id, text, markup = bot.sent[0]
    assert chat_id == 7
    assert text == (
        "🔔 <b>Освободились корты</b>\n\n"
        "<b>Понедельник, 21 сентября</b>\n"
        "Padel Port: 16:00 (Padel 1)"
    )
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert [(b.text, b.callback_data) for b in buttons] == [
        ("пн 16:00 · Padel Port", SlotCb(day="20260921", rng="w", v=0, hm="1600").pack())
    ]

    clock.now += STEP
    await poller.run_cycle()
    assert len(bot.sent) == 1  # remembered as notified


async def test_failed_send_is_repeated_next_cycle(venues, store):
    store.create(chat_id=7, lang="ru", day=MON, hour_from=16, now=T0 - timedelta(hours=1))
    bot = FakeBot()
    poller, clock, _ = await freed_slot_setup(venues, store, bot)
    bot.errors = [TelegramNetworkError(method=MagicMock(), message="down")]

    assert (await poller.run_cycle()).notified_chats == 0
    assert bot.sent == []

    clock.now += STEP
    assert (await poller.run_cycle()).notified_chats == 1
    assert len(bot.sent) == 1


async def test_two_subscriptions_make_one_message(venues, store):
    earlier = T0 - timedelta(hours=1)
    first = store.create(chat_id=7, lang="ru", day=MON, hour_from=16, now=earlier)
    second = store.create(chat_id=7, lang="en", day=MON, hour_from=15, hours=2, now=earlier)
    store.create(chat_id=8, lang="en", weekday=0, hour_from=16, now=earlier)
    bot = FakeBot()
    poller, _, _ = await freed_slot_setup(venues, store, bot)

    assert (await poller.run_cycle()).notified_chats == 2

    by_chat = {chat_id: text for chat_id, text, _ in bot.sent}
    assert by_chat[7].count("16:00") == 1
    assert "Courts are free" in by_chat[8]
    known = store.known_matches()
    key = ("pp", dt("2026-09-21T16:00:00"))
    assert known[first.id][key].notified_at is not None
    assert known[second.id][key].notified_at is not None


@pytest.mark.parametrize(
    "error",
    [
        TelegramForbiddenError(
            method=MagicMock(), message="Forbidden: bot was blocked by the user"
        ),
        TelegramForbiddenError(method=MagicMock(), message="Forbidden: user is deactivated"),
        TelegramBadRequest(method=MagicMock(), message="Bad Request: chat not found"),
    ],
)
async def test_unreachable_chat_loses_its_subscriptions(venues, store, error):
    store.create(chat_id=7, lang="ru", day=MON, hour_from=16, now=T0 - timedelta(hours=1))
    store.create(chat_id=8, lang="ru", day=MON, hour_from=20, now=T0 - timedelta(hours=1))
    bot = FakeBot()
    poller, _, _ = await freed_slot_setup(venues, store, bot)
    bot.errors = [error]

    await poller.run_cycle()

    assert store.list_for_chat(7, T0) == []
    assert len(store.list_for_chat(8, T0)) == 1


async def test_other_bad_request_keeps_subscriptions(venues, store):
    store.create(chat_id=7, lang="ru", day=MON, hour_from=16, now=T0 - timedelta(hours=1))
    bot = FakeBot()
    poller, _, _ = await freed_slot_setup(venues, store, bot)
    bot.errors = [
        TelegramBadRequest(method=MagicMock(), message="Bad Request: can't parse entities")
    ]

    await poller.run_cycle()

    assert len(store.list_for_chat(7, T0)) == 1


async def test_subscription_deleted_before_send_gets_no_message(venues, store, monkeypatch):
    store.create(chat_id=7, lang="ru", day=MON, hour_from=16, now=T0 - timedelta(hours=1))
    bot = FakeBot()
    poller, _, _ = await freed_slot_setup(venues, store, bot)
    apply_cycle = store.apply_cycle

    def apply_then_delete(plan, now):
        apply_cycle(plan, now)
        store.delete_chat(7)  # the user deletes it right after the cycle's writes

    monkeypatch.setattr(store, "apply_cycle", apply_then_delete)

    assert (await poller.run_cycle()).notified_chats == 0
    assert bot.sent == []


async def test_subscription_changed_during_send_is_rebaselined(venues, store):
    sub = store.create(chat_id=7, lang="ru", day=MON, hour_from=16, now=T0 - timedelta(hours=1))
    bot = FakeBot()
    poller, clock, _ = await freed_slot_setup(venues, store, bot)
    bot.on_send = lambda: store.update(replace(sub, hours=2), clock.now)

    assert (await poller.run_cycle()).notified_chats == 1  # already on its way
    assert store.known_matches() == {}  # not recorded for the old conditions

    bot.on_send = None
    clock.now += STEP
    await poller.run_cycle()

    assert len(bot.sent) == 1  # the next cycle remembers the slot silently
    key = ("pp", dt("2026-09-21T16:00:00"))
    assert store.known_matches()[sub.id][key].notified_at is None


async def test_telegram_retry_after_is_retried_once(venues, store):
    store.create(chat_id=7, lang="ru", day=MON, hour_from=16, now=T0 - timedelta(hours=1))
    bot = FakeBot()
    sleeps: list[float] = []
    poller, _, _ = await freed_slot_setup(venues, store, bot, sleeps)
    bot.errors = [
        TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=3)
    ]

    assert (await poller.run_cycle()).notified_chats == 1
    assert sleeps == [3]


async def test_no_subscriptions_no_requests(venues, store):
    client = FakeClient({})
    outcome = await make_poller(venues, store, client=client).run_cycle()
    assert outcome == CycleOutcome(ok=True)
    assert client.calls == []


async def test_whole_cycle_failure_reports_retry_after(venues, store):
    class RateLimited:
        async def get_slots(self, *args):
            raise ReservioError("429", retry_after=120)

    store.create(chat_id=7, lang="ru", day=MON, hour_from=16, now=T0)
    outcome = await make_poller(venues, store, client=RateLimited()).run_cycle()
    assert outcome == CycleOutcome(ok=False, retry_after=120)


async def test_failed_cycle_does_not_stop_the_loop(venues, store):
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    poller = Poller(
        FakeBot(),
        FakeClient({}),
        venues,
        store,
        600,
        jitter_seconds=0,
        clock=Clock(T0),
        sleep=sleep,
    )
    poller.run_cycle = AsyncMock(  # type: ignore[method-assign]
        side_effect=[RuntimeError("bug"), CycleOutcome(ok=False), CycleOutcome(ok=True)]
    )

    with pytest.raises(asyncio.CancelledError):
        await poller.run()

    assert poller.run_cycle.await_count == 3
    assert sleeps == [1200, 2400, 600]


async def test_loop_sleeps_through_the_night(venues, store):
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    poller = Poller(
        FakeBot(),
        FakeClient({}),
        venues,
        store,
        clock=Clock(dt("2026-09-15T03:00:00")),
        sleep=sleep,
    )
    poller.run_cycle = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await poller.run()

    assert sleeps == [4 * 3600 + 50 * 60]
    poller.run_cycle.assert_not_awaited()


def test_notification_shows_at_most_twenty_times(venues, store):
    venue = venues[0]
    court = venue.courts[0]
    free = {}
    for i in range(25):
        start = dt("2026-09-16T07:00:00") + timedelta(minutes=30 * i)
        raw = slot(f"{start:%Y-%m-%dT%H:%M:%S}")
        free[("pp", start)] = [court_slot(venue, court, court.services[0], raw)]
    plan = CyclePlan(ok_venues={"pp"}, service_states={}, subscriptions=[], free=free)

    text, markup = make_poller(venues, store).render(set(free), plan, "ru")

    assert text.count("(Padel 1)") == 20
    assert "16:30 (Padel 1)" in text and "17:00" not in text  # the earliest ones are kept
    assert text.endswith("и ещё 5")
    assert sum(len(row) for row in markup.inline_keyboard) == 20
    assert len(text) < 4096


def test_notification_groups_days_and_clubs(venues, store):
    def entry(venue_idx: int, court_idx: int, service_idx: int, start: str):
        venue = venues[venue_idx]
        court = venue.courts[court_idx]
        raw = slot(start)
        return court_slot(venue, court, court.services[service_idx], raw)

    free = {
        ("gp", dt("2026-09-21T17:00:00")): [entry(1, 0, 1, "2026-09-21T17:00:00")],
        ("pp", dt("2026-09-21T16:00:00")): [
            entry(0, 0, 0, "2026-09-21T16:00:00"),
            entry(0, 1, 0, "2026-09-21T16:00:00"),
        ],
        ("pp", dt("2026-09-22T01:00:00")): [entry(0, 1, 0, "2026-09-22T01:00:00")],
        # Beyond the days the bot shows: listed, but without a button.
        ("pp", dt("2026-09-22T10:00:00")): [entry(0, 0, 0, "2026-09-22T10:00:00")],
    }
    plan = CyclePlan(ok_venues={"pp", "gp"}, service_states={}, subscriptions=[], free=free)

    text, markup = make_poller(venues, store).render(set(free), plan, "en")

    assert text == (
        "🔔 <b>Courts are free</b>\n\n"
        "<b>Monday, 21 September</b>\n"
        "Padel Port: 16:00 (Padel 1, Padel 2), 01:00 (Padel 2)\n"
        "Grand Padel: 17:00 (Court A)\n\n"
        "<b>Tuesday, 22 September</b>\n"
        "Padel Port: 10:00 (Padel 1)"
    )
    buttons = [b.text for row in markup.inline_keyboard for b in row]
    assert buttons == [
        "Mon 16:00 · Padel Port",
        "Mon 01:00 · Padel Port",
        "Mon 17:00 · Grand Padel",
    ]
    assert all(len(b.callback_data.encode()) <= 64 for row in markup.inline_keyboard for b in row)
