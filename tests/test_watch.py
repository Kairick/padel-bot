from dataclasses import replace
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message

from padel_bot.bot import watch
from padel_bot.bot.i18n import WEEKLY, t
from padel_bot.bot.keyboards import DayCb, WatchCb, WatchDayCb, WatchHourCb, encode_day
from padel_bot.db import connect
from padel_bot.domain import TZ, current_play_day
from padel_bot.monitoring.models import Subscription
from padel_bot.monitoring.store import MAX_SUBSCRIPTIONS, SubscriptionStore
from padel_bot.reservio.service import Availability
from tests.conftest import dt

MON = date(2026, 9, 21)
NOW = dt("2026-09-15T12:00:00")  # Tuesday


def sub(**changes) -> Subscription:
    base = Subscription(
        id=1,
        chat_id=7,
        lang="ru",
        venue_key=None,
        day=MON,
        weekday=None,
        hour_from=16,
        hours=1,
        min_courts=1,
        changed_at=NOW,
    )
    return replace(base, **changes)


@pytest.fixture
def store(tmp_path):
    db = connect(tmp_path / "bot.sqlite3")
    yield SubscriptionStore(db)
    db.close()


def make_cb(chat_id: int = 7) -> MagicMock:
    cb = MagicMock()
    cb.from_user = MagicMock(id=chat_id, language_code="ru")
    cb.message = MagicMock(spec=Message)
    cb.message.chat = MagicMock(id=chat_id)
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def make_availability(venues) -> MagicMock:
    availability = MagicMock(venues=venues)
    availability.get_availability = AsyncMock(
        side_effect=lambda day, *a, **k: Availability(day=day, slots=[])
    )
    return availability


def edited_text(cb: MagicMock) -> str:
    return cb.message.edit_text.await_args.args[0]


def tomorrow() -> date:
    return current_play_day() + timedelta(days=1)


# Pure parts


def test_watch_hours():
    today = date(2026, 9, 15)
    assert watch.watch_hours(today, dt("2026-09-15T15:20:00"))[0] == 16
    assert watch.watch_hours(today, dt("2026-09-15T15:40:00"))[0] == 17
    assert watch.watch_hours(today, dt("2026-09-16T00:30:00")) == [25]
    assert watch.watch_hours(today, dt("2026-09-16T00:31:00")) == []
    assert watch.watch_hours(MON, NOW) == list(range(7, 26))


def test_toggle_length_cycles_and_ends_by_two():
    assert [watch.toggle_length(sub(hours=h)).hours for h in (1, 2, 3)] == [2, 3, 1]
    assert [watch.toggle_length(sub(hour_from=24, hours=h)).hours for h in (1, 2)] == [2, 1]
    assert watch.toggle_length(sub(hour_from=25)) == sub(hour_from=25)


def test_toggle_club_and_courts(venues):
    keys = []
    current = sub()
    for _ in range(3):
        current = watch.toggle_club(current, venues)
        keys.append(current.venue_key)
    assert keys == ["pp", "gp", None]
    assert watch.toggle_club(sub(venue_key="removed"), venues).venue_key == "pp"
    assert watch.toggle_courts(sub()).min_courts == 2
    assert watch.toggle_courts(sub(min_courts=2)).min_courts == 1


def test_toggle_kind():
    weekly = watch.toggle_kind(sub(), NOW)
    assert (weekly.day, weekly.weekday) == (None, 0)
    assert watch.toggle_kind(weekly, NOW).day == MON
    # On Monday itself, too close to 16:00: next week.
    assert watch.toggle_kind(weekly, dt("2026-09-21T15:40:00")).day == date(2026, 9, 28)
    assert watch.toggle_kind(weekly, dt("2026-09-21T15:20:00")).day == MON
    # 03:00 on Monday is still Sunday's play day, so Monday is later today.
    assert watch.toggle_kind(weekly, dt("2026-09-21T03:00:00")).day == MON
    # Monday 01:00 is the night after Monday: at 00:40 on Tuesday it's still coming.
    late = sub(day=None, weekday=0, hour_from=25)
    assert watch.toggle_kind(late, dt("2026-09-22T00:20:00")).day == MON
    assert watch.toggle_kind(late, dt("2026-09-22T00:40:00")).day == date(2026, 9, 28)


def buttons(markup) -> list[list[str]]:
    return [[b.text for b in row] for row in markup.inline_keyboard]


def test_card_view_for_a_date(venues):
    text, markup = watch.card_view(sub(), venues, "ru", NOW)

    assert text == (
        "🔔 <b>Слежу за кортами</b>\nПонедельник, 21 сентября · 16:00–17:00\nЛюбой клуб · 1 корт"
    )
    assert buttons(markup) == [
        ["🔁 Каждый понедельник"],
        ["⏱ 16:00–17:00", "👥 1 корт"],
        ["🏟 Любой клуб"],
        ["🗑 Удалить", "✓ Готово"],
    ]


def test_card_view_weekly(venues):
    weekly = sub(day=None, weekday=2, hour_from=25, venue_key="gp", min_courts=2)

    text, markup = watch.card_view(weekly, venues, "ru", NOW)

    assert text.splitlines()[1:] == ["Каждую среду · 01:00–02:00", "Grand Padel · 2 корта"]
    assert buttons(markup)[0] == ["📅 Только 16 сентября"]
    en_text, en_markup = watch.card_view(weekly, venues, "en", NOW)
    assert en_text.splitlines()[1] == "Every Wednesday · 01:00–02:00"
    assert buttons(en_markup)[0] == ["📅 Only 16 September"]


def test_views_fit_callback_data_limit(venues):
    big = sub(id=2**40)
    markups = [
        watch.card_view(big, venues, "ru", NOW)[1],
        watch.subs_view([big, sub(day=None, weekday=6)], venues, "en")[1],
        watch.hours_view(MON, "e", "ru", NOW)[1],
    ]
    assert all(
        len(b.callback_data.encode()) <= 64
        for m in markups
        for row in m.inline_keyboard
        for b in row
        if b.callback_data
    )


def test_hours_view(venues):
    text, markup = watch.hours_view(MON, "e", "ru", NOW)
    rows = buttons(markup)
    assert text == "📅 <b>Понедельник, 21 сентября</b>\nС какого часа следить?"
    assert rows[0] == ["07:00", "08:00", "09:00", "10:00"]
    assert rows[-2] == ["23:00", "00:00", "01:00"]
    assert rows[-1] == ["⬅️ Назад"]

    text, markup = watch.hours_view(date(2026, 9, 15), "w", "ru", dt("2026-09-16T01:00:00"))
    assert text.endswith(t("ru", "watch_no_hours"))
    assert buttons(markup) == [["⬅️ Назад"]]


def test_subs_view(venues):
    subs = [sub(), sub(id=2, day=None, weekday=0, venue_key="pp", min_courts=2)]
    text, markup = watch.subs_view(subs, venues, "ru")
    assert text == t("ru", "subs_title")
    assert buttons(markup) == [
        ["пн 21.09 16:00–17:00 · Любой клуб · 1 корт"],
        ["🔁 пн 16:00–17:00 · Padel Port · 2 корта"],
        ["➕ Новая подписка"],
    ]
    full = [sub(id=i) for i in range(MAX_SUBSCRIPTIONS)]
    assert "➕ Новая подписка" not in sum(buttons(watch.subs_view(full, venues, "ru")[1]), [])
    text, _ = watch.subs_view([], venues, "ru", notice="Подписка удалена")
    assert text == f"Подписка удалена\n\n{t('ru', 'subs_empty')}"


# Handlers


async def test_hour_tap_creates_subscription_once(venues, store):
    day = tomorrow()
    stats = MagicMock()
    data = WatchHourCb(day=encode_day(day), hour=16)

    for _ in range(2):
        cb = make_cb()
        await watch.on_watch_hour(cb, data, store, make_availability(venues), stats)
        assert edited_text(cb).startswith(t("ru", "watch_title"))

    subs = store.list_for_chat(7, datetime.now(TZ))
    assert [(s.day, s.hour_from, s.hours, s.venue_key, s.min_courts) for s in subs] == [
        (day, 16, 1, None, 1)
    ]
    stats.track_event.assert_called_once_with("watch_created")


async def test_hour_tap_at_the_limit_shows_subscriptions(venues, store):
    day = tomorrow()
    for hour in range(8, 8 + MAX_SUBSCRIPTIONS):
        store.create(chat_id=7, lang="ru", day=day, hour_from=hour)
    cb = make_cb()

    await watch.on_watch_hour(
        cb, WatchHourCb(day=encode_day(day), hour=20), store, make_availability(venues), MagicMock()
    )

    assert edited_text(cb).startswith(t("ru", "watch_limit", limit=MAX_SUBSCRIPTIONS))
    assert store.count_for_chat(7) == MAX_SUBSCRIPTIONS


async def test_invalid_hour_is_rejected(venues, store):
    cb = make_cb()
    data = WatchHourCb(day=encode_day(tomorrow()), hour=99)

    await watch.on_watch_hour(cb, data, store, make_availability(venues), MagicMock())

    cb.answer.assert_awaited_once_with(t("ru", "stale_button"), show_alert=True)
    assert not store.has_subscriptions()


async def test_card_of_another_chat_is_stale(venues, store):
    other = store.create(chat_id=8, lang="ru", day=tomorrow(), hour_from=16)
    for data in (WatchCb(sid=other.id, action="del"), WatchCb(sid=999, action="open")):
        cb = make_cb(chat_id=7)
        await watch.on_watch_card(cb, data, store, make_availability(venues), MagicMock())
        cb.answer.assert_awaited_once_with(t("ru", "stale_button"), show_alert=True)
    assert store.get(other.id) == other


async def test_toggle_saves_and_rejects_copies(venues, store):
    day = tomorrow()
    first = store.create(chat_id=7, lang="en", day=day, hour_from=16)
    store.create(chat_id=7, lang="en", day=day, hour_from=16, hours=3)
    availability = make_availability(venues)

    cb = make_cb()
    await watch.on_watch_card(
        cb, WatchCb(sid=first.id, action="len"), store, availability, MagicMock()
    )
    saved = store.get(first.id)
    assert saved is not None
    assert saved.hours == 2 and saved.changed_at > first.changed_at
    assert saved.lang == "ru"  # language follows the latest action
    assert "16:00–18:00" in edited_text(cb)

    cb = make_cb()
    await watch.on_watch_card(
        cb, WatchCb(sid=first.id, action="len"), store, availability, MagicMock()
    )
    cb.answer.assert_awaited_once_with(t("ru", "watch_duplicate"), show_alert=True)
    cb.message.edit_text.assert_not_awaited()
    assert store.get(first.id) == saved


async def test_delete_shows_the_list(venues, store):
    created = store.create(chat_id=7, lang="ru", day=tomorrow(), hour_from=16)
    stats = MagicMock()
    cb = make_cb()

    await watch.on_watch_card(
        cb, WatchCb(sid=created.id, action="del"), store, make_availability(venues), stats
    )

    assert not store.has_subscriptions()
    assert edited_text(cb) == f"{t('ru', 'watch_deleted')}\n\n{t('ru', 'subs_empty')}"
    stats.track_event.assert_called_once_with("watch_deleted")


async def test_done_opens_the_day(venues, store):
    day = tomorrow()
    created = store.create(chat_id=7, lang="ru", day=day, hour_from=16)
    availability = make_availability(venues)
    cb = make_cb()

    await watch.on_watch_card(
        cb, WatchCb(sid=created.id, action="done"), store, availability, MagicMock()
    )

    assert availability.get_availability.await_args.args[0] == day
    assert edited_text(cb).startswith("📅 <b>")


async def test_subs_command(venues, store):
    store.create(chat_id=7, lang="en", day=tomorrow(), hour_from=16)
    message = MagicMock(from_user=MagicMock(language_code="ru"), chat=MagicMock(id=7))
    message.answer = AsyncMock()

    await watch.cmd_subs(message, store, make_availability(venues))

    assert message.answer.await_args.args[0] == t("ru", "subs_title")
    assert store.list_for_chat(7, datetime.now(TZ))[0].lang == "ru"


async def test_watch_day_opens_the_hour_grid():
    day = tomorrow()
    cb = make_cb()

    await watch.on_watch_day(cb, WatchDayCb(day=encode_day(day), rng="e"))

    assert edited_text(cb).endswith(t("ru", "watch_pick_hour"))
    markup = cb.message.edit_text.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[-1][0].callback_data == DayCb(day=encode_day(day), rng="e").pack()


async def test_kind_toggle_switches_to_weekly(venues, store):
    day = tomorrow()
    created = store.create(chat_id=7, lang="ru", day=day, hour_from=16)
    cb = make_cb()

    await watch.on_watch_card(
        cb, WatchCb(sid=created.id, action="kind"), store, make_availability(venues), MagicMock()
    )

    saved = store.get(created.id)
    assert saved is not None
    assert (saved.day, saved.weekday) == (None, day.weekday())
    assert WEEKLY["ru"][day.weekday()] in edited_text(cb)


def test_card_view_escapes_club_name(venues):
    renamed = [venues[0], venues[1].model_copy(update={"name": "Sea & Road"})]

    text, markup = watch.card_view(sub(venue_key="gp"), renamed, "ru", NOW)

    assert text.endswith("Sea &amp; Road · 1 корт")
    assert buttons(markup)[2] == ["🏟 Sea & Road"]  # button labels are plain text
