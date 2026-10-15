"""Subscriptions to freed courts: the Watch button, hour grid, subscription card, /watch, /subs.

Stateless: everything a step needs is in the callback data or in the stored subscription.
"""

from dataclasses import replace
from datetime import date, datetime
from html import escape

from aiogram import F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from padel_bot.bot.common import (
    answer_quietly,
    build_day_view,
    lang_of,
    private_router,
    resolve_day,
    safe_edit,
)
from padel_bot.bot.formatting import day_title, render_notification
from padel_bot.bot.i18n import MONTHS, WEEKDAYS_SHORT, WEEKLY, t
from padel_bot.bot.keyboards import (
    DEFAULT_RANGE,
    WATCH,
    DayCb,
    WatchCb,
    WatchDayCb,
    WatchHourCb,
    days_keyboard,
    encode_day,
    normalize_range,
    notification_keyboard,
    parse_day,
)
from padel_bot.domain import TZ, Lang, current_play_day
from padel_bot.monitoring.models import (
    FIRST_HOUR,
    LAST_END_HOUR,
    LAST_HOUR,
    LEAD_TIME,
    MAX_HOURS,
    FreedTime,
    Subscription,
    nearest_day,
    slot_start,
)
from padel_bot.monitoring.store import (
    MAX_SUBSCRIPTIONS,
    DuplicateSubscriptionError,
    SubscriptionLimitError,
    SubscriptionStore,
)
from padel_bot.reservio.models import Venue
from padel_bot.reservio.service import AvailabilityService
from padel_bot.stats import Stats

watch_router = private_router("watch")

TOGGLES = ("kind", "len", "club", "courts")


def notification_message(
    freed: list[FreedTime], venues: list[Venue], hidden: int, today: date, lang: Lang
) -> tuple[str, InlineKeyboardMarkup]:
    """Text and buttons of a freed-courts notification; the monitor sends it."""
    text = render_notification(freed, venues, hidden, lang)
    starts = [(venue, day, start) for venue, day, start, _ in freed]
    return text, notification_keyboard(starts, venues, today, lang)


def hour_label(hour: int) -> str:
    return f"{hour % 24:02d}:00"


def range_label(sub: Subscription) -> str:
    return f"{hour_label(sub.hour_from)}–{hour_label(sub.hour_from + sub.hours)}"


def short_date(day: date, lang: Lang) -> str:
    return f"{day.day} {MONTHS[lang][day.month - 1]}"


def club_label(sub: Subscription, venues: list[Venue], lang: Lang) -> str:
    if sub.venue_key is None:
        return t(lang, "watch_any_club")
    return next((v.name for v in venues if v.key == sub.venue_key), sub.venue_key)


def watch_hours(day: date, now: datetime) -> list[int]:
    """Hours of `day` still worth watching: at least LEAD_TIME before they start."""
    return [h for h in range(FIRST_HOUR, LAST_HOUR + 1) if slot_start(day, h) - now >= LEAD_TIME]


# Card toggles: pure, return the subscription unchanged when there's nothing to switch.


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


# Views


def hours_view(day: date, rng: str, lang: Lang, now: datetime) -> tuple[str, InlineKeyboardMarkup]:
    hours = watch_hours(day, now)
    prompt = t(lang, "watch_pick_hour" if hours else "watch_no_hours")
    text = f"📅 <b>{day_title(day, lang)}</b>\n{prompt}"
    buttons = [
        InlineKeyboardButton(
            text=hour_label(h), callback_data=WatchHourCb(day=encode_day(day), hour=h).pack()
        )
        for h in hours
    ]
    rows = [buttons[i : i + 4] for i in range(0, len(buttons), 4)]
    rows.append(
        [
            InlineKeyboardButton(
                text=t(lang, "back"),
                callback_data=DayCb(day=encode_day(day), rng=normalize_range(rng)).pack(),
            )
        ]
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def card_view(
    sub: Subscription, venues: list[Venue], lang: Lang, now: datetime
) -> tuple[str, InlineKeyboardMarkup]:
    if sub.day is not None:
        when = day_title(sub.day, lang)
        kind_button = f"🔁 {WEEKLY[lang][sub.day.weekday()]}"
    else:
        assert sub.weekday is not None
        when = WEEKLY[lang][sub.weekday]
        day = nearest_day(sub.weekday, sub.hour_from, now)
        kind_button = t(lang, "watch_only_day", day=short_date(day, lang))
    courts = t(lang, f"watch_courts_{sub.min_courts}")
    text = "\n".join(
        [
            t(lang, "watch_title"),
            f"{when} · {range_label(sub)}",
            f"{escape(club_label(sub, venues, lang))} · {courts}",
        ]
    )

    def button(label: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=label, callback_data=WatchCb(sid=sub.id, action=action).pack()
        )

    rows = [
        [button(kind_button, "kind")],
        [button(f"⏱ {range_label(sub)}", "len"), button(f"👥 {courts}", "courts")],
        [button(f"🏟 {club_label(sub, venues, lang)}", "club")],
        [button(t(lang, "watch_delete"), "del"), button(t(lang, "watch_done"), "done")],
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_label(sub: Subscription, venues: list[Venue], lang: Lang) -> str:
    if sub.day is not None:
        when = f"{WEEKDAYS_SHORT[lang][sub.day.weekday()]} {sub.day:%d.%m}"
    else:
        assert sub.weekday is not None
        when = f"🔁 {WEEKDAYS_SHORT[lang][sub.weekday]}"
    courts = t(lang, f"watch_courts_{sub.min_courts}")
    return f"{when} {range_label(sub)} · {club_label(sub, venues, lang)} · {courts}"


def subs_view(
    subs: list[Subscription], venues: list[Venue], lang: Lang, notice: str | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    text = t(lang, "subs_title" if subs else "subs_empty")
    if notice:
        text = f"{notice}\n\n{text}"
    rows = [
        [
            InlineKeyboardButton(
                text=subscription_label(sub, venues, lang),
                callback_data=WatchCb(sid=sub.id, action="open").pack(),
            )
        ]
        for sub in subs
    ]
    if len(subs) < MAX_SUBSCRIPTIONS:
        rows.append([InlineKeyboardButton(text=t(lang, "subs_new"), callback_data=WATCH)])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


# Handlers


@watch_router.message(Command("watch"))
async def cmd_watch(message: Message) -> None:
    lang = lang_of(message.from_user)
    await message.answer(
        t(lang, "watch_start"), reply_markup=days_keyboard(current_play_day(), lang)
    )


@watch_router.message(Command("subs"))
async def cmd_subs(
    message: Message, subscriptions: SubscriptionStore, availability: AvailabilityService
) -> None:
    lang = lang_of(message.from_user)
    subscriptions.set_lang(message.chat.id, lang)
    subs = subscriptions.list_for_chat(message.chat.id, datetime.now(TZ))
    text, markup = subs_view(subs, availability.venues, lang)
    await message.answer(text, reply_markup=markup)


@watch_router.callback_query(F.data == WATCH)
async def on_watch_start(cb: CallbackQuery) -> None:
    await answer_quietly(cb)
    lang = lang_of(cb.from_user)
    if isinstance(cb.message, Message):
        await safe_edit(cb.message, t(lang, "watch_start"), days_keyboard(current_play_day(), lang))


@watch_router.callback_query(WatchDayCb.filter())
async def on_watch_day(cb: CallbackQuery, callback_data: WatchDayCb) -> None:
    lang = lang_of(cb.from_user)
    if (resolved := await resolve_day(cb, callback_data.day, lang)) is None:
        return
    message, day = resolved
    await answer_quietly(cb)
    text, markup = hours_view(day, callback_data.rng, lang, datetime.now(TZ))
    await safe_edit(message, text, markup)


@watch_router.callback_query(WatchHourCb.filter())
async def on_watch_hour(
    cb: CallbackQuery,
    callback_data: WatchHourCb,
    subscriptions: SubscriptionStore,
    availability: AvailabilityService,
    stats: Stats,
) -> None:
    lang = lang_of(cb.from_user)
    if (resolved := await resolve_day(cb, callback_data.day, lang)) is None:
        return
    message, day = resolved
    now = datetime.now(TZ)
    if callback_data.hour not in watch_hours(day, now):
        # An old grid: the hour has passed meanwhile, or the data is forged.
        await answer_quietly(cb, t(lang, "stale_button"), show_alert=True)
        text, markup = hours_view(day, DEFAULT_RANGE, lang, now)
        await safe_edit(message, text, markup)
        return

    chat_id = message.chat.id
    venues = availability.venues
    try:
        sub = subscriptions.create(
            chat_id=chat_id, lang=lang, day=day, hour_from=callback_data.hour, now=now
        )
    except DuplicateSubscriptionError as e:
        existing = subscriptions.get(e.existing_id)
        if existing is None:
            await answer_quietly(cb, t(lang, "stale_button"), show_alert=True)
            return
        sub = existing
    except SubscriptionLimitError:
        await answer_quietly(cb)
        notice = t(lang, "watch_limit", limit=MAX_SUBSCRIPTIONS)
        subs = subscriptions.list_for_chat(chat_id, now)
        text, markup = subs_view(subs, venues, lang, notice)
        await safe_edit(message, text, markup)
        return
    else:
        stats.track_event("watch_created")
    await answer_quietly(cb)
    text, markup = card_view(sub, venues, lang, now)
    await safe_edit(message, text, markup)


@watch_router.callback_query(WatchCb.filter())
async def on_watch_card(
    cb: CallbackQuery,
    callback_data: WatchCb,
    subscriptions: SubscriptionStore,
    availability: AvailabilityService,
    stats: Stats,
) -> None:
    lang = lang_of(cb.from_user)
    if not isinstance(cb.message, Message):
        await answer_quietly(cb, t(lang, "stale_button"), show_alert=True)
        return
    chat_id = cb.message.chat.id
    sub = subscriptions.get(callback_data.sid)
    if sub is None or sub.chat_id != chat_id:
        await answer_quietly(cb, t(lang, "stale_button"), show_alert=True)
        return
    subscriptions.set_lang(chat_id, lang)
    venues = availability.venues
    now = datetime.now(TZ)
    action = callback_data.action

    if action == "open":
        await answer_quietly(cb)
        await safe_edit(cb.message, *card_view(sub, venues, lang, now))
    elif action == "del":
        subscriptions.delete(sub.id, chat_id)
        stats.track_event("watch_deleted")
        await answer_quietly(cb)
        subs = subscriptions.list_for_chat(chat_id, now)
        await safe_edit(cb.message, *subs_view(subs, venues, lang, t(lang, "watch_deleted")))
    elif action == "done":
        await answer_quietly(cb)
        today = current_play_day(now)
        day = sub.day if sub.day is not None else nearest_day(sub.weekday or 0, sub.hour_from, now)
        if parse_day(encode_day(day), today) is None:
            await safe_edit(cb.message, t(lang, "pick_day"), days_keyboard(today, lang))
            return
        stats.track_event("day_view")
        await safe_edit(cb.message, *await build_day_view(availability, day, DEFAULT_RANGE, lang))
    elif action in TOGGLES:
        updated = {
            "kind": lambda: toggle_kind(sub, now),
            "len": lambda: toggle_length(sub),
            "club": lambda: toggle_club(sub, venues),
            "courts": lambda: toggle_courts(sub),
        }[action]()
        if updated == sub:
            await answer_quietly(cb)
            return
        try:
            sub = subscriptions.update(updated, now)
        except DuplicateSubscriptionError:
            await answer_quietly(cb, t(lang, "watch_duplicate"), show_alert=True)
            return
        await answer_quietly(cb)
        await safe_edit(cb.message, *card_view(sub, venues, lang, now))
    else:
        await answer_quietly(cb, t(lang, "stale_button"), show_alert=True)
