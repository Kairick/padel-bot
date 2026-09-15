import logging
from datetime import date, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, User

from padel_bot.bot.formatting import render_day, render_slot
from padel_bot.bot.i18n import Lang, detect_lang, t
from padel_bot.bot.keyboards import (
    DAYS,
    DEFAULT_RANGE,
    NOOP,
    RANGES,
    DayCb,
    SlotCb,
    day_keyboard,
    days_keyboard,
    normalize_range,
    parse_day,
    slot_keyboard,
    try_decode_day,
)
from padel_bot.bot.throttle import RateLimiter
from padel_bot.reservio.service import AvailabilityService, current_play_day
from padel_bot.stats import Stats, format_summary

log = logging.getLogger(__name__)

# Booking links are Reservio draft orders: anyone who sees the message can open them.
# So the bot works only in private chats and only with its own messages: a forwarded copy
# of a bot message in someone else's chat can't be edited and must not create orders.
router = Router(name="private")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(
    F.message.chat.type == ChatType.PRIVATE,
    F.message.from_user.is_bot,
)

# Included after `router`: group commands, plus every callback the private router rejected
# (groups, forwarded copies, inaccessible or inline messages), so no tap stays unanswered.
group_router = Router(name="fallback")
group_router.message.filter(F.chat.type != ChatType.PRIVATE)


def lang_of(user: User | None) -> Lang:
    return detect_lang(user.language_code if user else None)


async def answer_quietly(cb: CallbackQuery, text: str | None = None, show_alert: bool = False):
    """Answer a callback, ignoring Telegram's refusal for stale queries.

    Taps made while the bot was down arrive after restart and can't be answered anymore,
    but the message can still be updated, so the handler must go on.
    """
    try:
        await cb.answer(text, show_alert=show_alert)
    except TelegramBadRequest as e:
        log.info("callback answer skipped: %s", e)


async def build_day_view(
    availability: AvailabilityService, day: date, rng: str, lang: Lang, refresh: bool = False
) -> tuple[str, InlineKeyboardMarkup]:
    rng = normalize_range(rng)
    result = await availability.get_availability(day, RANGES[rng], force_refresh=refresh)
    text = render_day(result, availability.venues, rng, lang)
    return text, day_keyboard(result, availability.venues, rng, lang)


async def safe_edit(message: Message, text: str, markup: InlineKeyboardMarkup) -> None:
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def resolve_day(cb: CallbackQuery, message: Message, value: str, lang: Lang) -> date | None:
    """Day from callback data if it can be shown; otherwise handle the tap and return None.

    A well-formed day outside the booking window (typically yesterday's message after
    06:00) reopens the day picker, so the message stays usable. Garbage gets an alert.
    """
    today = current_play_day()
    day = parse_day(value, today)
    if day is not None:
        return day
    if try_decode_day(value) is None:
        await answer_quietly(cb, t(lang, "stale_button"), show_alert=True)
    else:
        await answer_quietly(cb)
        await safe_edit(message, t(lang, "pick_day"), days_keyboard(today, lang))
    return None


@router.message(CommandStart())
@router.message(Command("days"))
async def cmd_start(message: Message, stats: Stats) -> None:
    lang = lang_of(message.from_user)
    stats.track_event("start")
    await message.answer(t(lang, "welcome"), reply_markup=days_keyboard(current_play_day(), lang))


@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    stats: Stats,
    admin_ids: frozenset[int],
    availability: AvailabilityService,
) -> None:
    user = message.from_user
    if user is None:
        return
    if not admin_ids:
        await message.answer(t(lang_of(user), "stats_disabled", user_id=user.id))
        return
    if user.id not in admin_ids:
        return
    venue_names = {v.key: v.name for v in availability.venues}
    await message.answer(format_summary(stats.summary(), venue_names))


@router.message(Command("today"))
async def cmd_today(message: Message, availability: AvailabilityService, stats: Stats) -> None:
    lang = lang_of(message.from_user)
    stats.track_event("day_view")
    text, markup = await build_day_view(availability, current_play_day(), DEFAULT_RANGE, lang)
    await message.answer(text, reply_markup=markup)


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message, availability: AvailabilityService, stats: Stats) -> None:
    lang = lang_of(message.from_user)
    stats.track_event("day_view")
    day = current_play_day() + timedelta(days=1)
    text, markup = await build_day_view(availability, day, DEFAULT_RANGE, lang)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == NOOP)
async def on_noop(cb: CallbackQuery) -> None:
    await answer_quietly(cb)


@router.callback_query(F.data == DAYS)
async def on_days(cb: CallbackQuery) -> None:
    await answer_quietly(cb)
    lang = lang_of(cb.from_user)
    if isinstance(cb.message, Message):
        await safe_edit(cb.message, t(lang, "pick_day"), days_keyboard(current_play_day(), lang))


@router.callback_query(DayCb.filter())
async def on_day(
    cb: CallbackQuery,
    callback_data: DayCb,
    availability: AvailabilityService,
    stats: Stats,
    refresh_limiter: RateLimiter,
) -> None:
    lang = lang_of(cb.from_user)
    if not isinstance(cb.message, Message):
        await answer_quietly(cb, t(lang, "stale_button"), show_alert=True)
        return
    day = await resolve_day(cb, cb.message, callback_data.day, lang)
    if day is None:
        return
    refresh = callback_data.refresh
    if refresh and not refresh_limiter.allow(cb.from_user.id):
        await answer_quietly(cb, t(lang, "too_many_requests"), show_alert=True)
        return
    stats.track_event("refresh" if refresh else "day_view")
    await answer_quietly(cb, t(lang, "refreshing") if refresh else None)
    text, markup = await build_day_view(availability, day, callback_data.rng, lang, refresh=refresh)
    await safe_edit(cb.message, text, markup)


@router.callback_query(SlotCb.filter())
async def on_slot(
    cb: CallbackQuery,
    callback_data: SlotCb,
    availability: AvailabilityService,
    stats: Stats,
    slot_limiter: RateLimiter,
) -> None:
    lang = lang_of(cb.from_user)
    venues = availability.venues
    if not isinstance(cb.message, Message) or not 0 <= callback_data.v < len(venues):
        await answer_quietly(cb, t(lang, "stale_button"), show_alert=True)
        return
    day = await resolve_day(cb, cb.message, callback_data.day, lang)
    if day is None:
        return
    if not slot_limiter.allow(cb.from_user.id):
        await answer_quietly(cb, t(lang, "too_many_requests"), show_alert=True)
        return
    # Answer right away: Telegram rejects late answers, and Reservio may be slow.
    await answer_quietly(cb)

    venue = venues[callback_data.v]
    rng = normalize_range(callback_data.rng)
    result = await availability.get_availability(day, RANGES[rng])
    slots = sorted(
        (s for s in result.by_venue().get(venue.key, []) if f"{s.start:%H%M}" == callback_data.hm),
        key=lambda s: s.court.name,
    )
    if not slots:
        # No slot can mean it was booked, or that Reservio didn't answer for this club.
        if any(v.key == venue.key for v in result.failed_venues):
            notice = f"⚠️ {escape(venue.name)}: {t(lang, 'venue_failed')}"
        else:
            notice = t(lang, "slot_taken")
        text, markup = await build_day_view(availability, day, rng, lang)
        await safe_edit(cb.message, f"{notice}\n\n{text}", markup)
        return
    stats.track_event("slot_view", venue=venue.key, hour=slots[0].start.hour)
    links = await availability.booking_links(slots, user_id=cb.from_user.id)
    await safe_edit(
        cb.message,
        render_slot(venue, day, slots[0].start, slots, lang),
        slot_keyboard(list(zip(slots, links, strict=True)), day, rng, lang),
    )


@group_router.message(Command("start", "days", "today", "tomorrow", "stats"))
async def on_group_command(message: Message, bot: Bot) -> None:
    me = await bot.me()
    link = f"https://t.me/{me.username}"
    await message.answer(t(lang_of(message.from_user), "private_only", link=link))


@group_router.callback_query()
async def on_foreign_callback(cb: CallbackQuery) -> None:
    in_group = cb.message is not None and cb.message.chat.type != ChatType.PRIVATE
    key = "private_only_short" if in_group else "stale_button"
    await answer_quietly(cb, t(lang_of(cb.from_user), key), show_alert=True)
