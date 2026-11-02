from datetime import date, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from padel_bot.bot.common import (
    answer_quietly,
    build_day_view,
    group_router,
    lang_of,
    link_target,
    private_router,
    resolve_day,
    safe_edit,
)
from padel_bot.bot.formatting import render_slot
from padel_bot.bot.i18n import t
from padel_bot.bot.keyboards import (
    DAYS,
    DEFAULT_RANGE,
    NOOP,
    RANGES,
    DayCb,
    SlotCb,
    WatchDayCb,
    days_keyboard,
    is_start_link,
    normalize_range,
    parse_day,
    parse_start_link,
    slot_keyboard,
)
from padel_bot.bot.throttle import RateLimiter
from padel_bot.domain import Lang, current_play_day
from padel_bot.reservio.service import AvailabilityService
from padel_bot.stats import Stats, format_summary

browse_router = private_router("private")
# Free slots in groups; the day view there links slots to the private chat.
group_browse_router = group_router("group")

# Included last: group commands that need the private chat, plus every callback the routers
# above rejected (forwarded copies, inaccessible or inline messages, private buttons in groups),
# so no tap stays unanswered.
fallback_router = Router(name="fallback")
fallback_router.message.filter(F.chat.type != ChatType.PRIVATE)


@browse_router.message(CommandStart(deep_link=True, magic=is_start_link(SlotCb)))
async def cmd_start_slot(
    message: Message,
    command: CommandObject,
    availability: AvailabilityService,
    stats: Stats,
    slot_limiter: RateLimiter,
) -> None:
    """A slot button of a group message: its booking links, in the private chat."""
    user = message.from_user
    lang = lang_of(user)
    data = parse_start_link(command.args, SlotCb)
    day = parse_day(data.day, current_play_day()) if data else None
    if user is None or data is None or day is None or not 0 <= data.v < len(availability.venues):
        # An old group message (the day has passed) or garbage: start over.
        await cmd_start(message, stats)
        return
    if not slot_limiter.allow(user.id):
        await message.answer(t(lang, "too_many_requests"))
        return
    text, markup = await slot_view(availability, stats, data, day, user.id, lang)
    await message.answer(text, reply_markup=markup)


# Not for the Watch links: watch_router opens those.
@browse_router.message(CommandStart(magic=~is_start_link(WatchDayCb)))
@browse_router.message(Command("days"))
@group_browse_router.message(Command("start", "days"))
async def cmd_start(message: Message, stats: Stats) -> None:
    lang = lang_of(message.from_user)
    stats.track_event("start")
    await message.answer(t(lang, "welcome"), reply_markup=days_keyboard(current_play_day(), lang))


@browse_router.message(Command("stats"))
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


async def answer_day_view(
    message: Message, availability: AvailabilityService, stats: Stats, bot: Bot, day: date
) -> None:
    lang = lang_of(message.from_user)
    stats.track_event("day_view")
    username = await link_target(message.chat.type, bot)
    text, markup = await build_day_view(
        availability, day, DEFAULT_RANGE, lang, bot_username=username
    )
    await message.answer(text, reply_markup=markup)


@browse_router.message(Command("today"))
@group_browse_router.message(Command("today"))
async def cmd_today(
    message: Message, availability: AvailabilityService, stats: Stats, bot: Bot
) -> None:
    await answer_day_view(message, availability, stats, bot, current_play_day())


@browse_router.message(Command("tomorrow"))
@group_browse_router.message(Command("tomorrow"))
async def cmd_tomorrow(
    message: Message, availability: AvailabilityService, stats: Stats, bot: Bot
) -> None:
    day = current_play_day() + timedelta(days=1)
    await answer_day_view(message, availability, stats, bot, day)


@browse_router.callback_query(F.data == NOOP)
@group_browse_router.callback_query(F.data == NOOP)
async def on_noop(cb: CallbackQuery) -> None:
    await answer_quietly(cb)


@browse_router.callback_query(F.data == DAYS)
@group_browse_router.callback_query(F.data == DAYS)
async def on_days(cb: CallbackQuery) -> None:
    await answer_quietly(cb)
    lang = lang_of(cb.from_user)
    if isinstance(cb.message, Message):
        await safe_edit(cb.message, t(lang, "pick_day"), days_keyboard(current_play_day(), lang))


@browse_router.callback_query(DayCb.filter())
@group_browse_router.callback_query(DayCb.filter())
async def on_day(
    cb: CallbackQuery,
    callback_data: DayCb,
    availability: AvailabilityService,
    stats: Stats,
    refresh_limiter: RateLimiter,
    bot: Bot,
) -> None:
    lang = lang_of(cb.from_user)
    if (resolved := await resolve_day(cb, callback_data.day, lang)) is None:
        return
    message, day = resolved
    refresh = callback_data.refresh
    if refresh and not refresh_limiter.allow(cb.from_user.id):
        await answer_quietly(cb, t(lang, "too_many_requests"), show_alert=True)
        return
    stats.track_event("refresh" if refresh else "day_view")
    await answer_quietly(cb, t(lang, "refreshing") if refresh else None)
    username = await link_target(message.chat.type, bot)
    text, markup = await build_day_view(
        availability, day, callback_data.rng, lang, refresh=refresh, bot_username=username
    )
    await safe_edit(message, text, markup)


@browse_router.callback_query(SlotCb.filter())
async def on_slot(
    cb: CallbackQuery,
    callback_data: SlotCb,
    availability: AvailabilityService,
    stats: Stats,
    slot_limiter: RateLimiter,
) -> None:
    lang = lang_of(cb.from_user)
    venues = availability.venues
    if not 0 <= callback_data.v < len(venues):
        await answer_quietly(cb, t(lang, "stale_button"), show_alert=True)
        return
    if (resolved := await resolve_day(cb, callback_data.day, lang)) is None:
        return
    message, day = resolved
    if not slot_limiter.allow(cb.from_user.id):
        await answer_quietly(cb, t(lang, "too_many_requests"), show_alert=True)
        return
    # Answer right away: Telegram rejects late answers, and Reservio may be slow.
    await answer_quietly(cb)
    text, markup = await slot_view(availability, stats, callback_data, day, cb.from_user.id, lang)
    await safe_edit(message, text, markup)


async def slot_view(
    availability: AvailabilityService,
    stats: Stats,
    data: SlotCb,
    day: date,
    user_id: int,
    lang: Lang,
) -> tuple[str, InlineKeyboardMarkup]:
    """Booking links of a slot, or the day view with a notice if it's gone. Private only."""
    venue = availability.venues[data.v]
    rng = normalize_range(data.rng)
    result = await availability.get_availability(day, RANGES[rng])
    slots = sorted(
        (s for s in result.by_venue().get(venue.key, []) if f"{s.start:%H%M}" == data.hm),
        key=lambda s: s.court.name,
    )
    if not slots:
        # No slot can mean it was booked, or that Reservio didn't answer for this club.
        if any(v.key == venue.key for v in result.failed_venues):
            notice = f"⚠️ {escape(venue.name)}: {t(lang, 'venue_failed')}"
        else:
            notice = t(lang, "slot_taken")
        text, markup = await build_day_view(availability, day, rng, lang)
        return f"{notice}\n\n{text}", markup
    stats.track_event("slot_view", venue=venue.key, hour=slots[0].start.hour)
    links = await availability.booking_links(slots, user_id=user_id)
    text = render_slot(venue, day, slots[0].start, slots, lang)
    return text, slot_keyboard(list(zip(slots, links, strict=True)), day, rng, lang)


# Not /stats: it's for admins, a group doesn't need to learn it exists.
@fallback_router.message(Command("watch", "subs", "feedback"))
async def on_group_command(message: Message, bot: Bot) -> None:
    me = await bot.me()
    link = f"https://t.me/{me.username}"
    await message.answer(t(lang_of(message.from_user), "private_only", link=link))


@fallback_router.callback_query()
async def on_foreign_callback(cb: CallbackQuery) -> None:
    in_group = cb.message is not None and cb.message.chat.type != ChatType.PRIVATE
    key = "private_only_short" if in_group else "stale_button"
    await answer_quietly(cb, t(lang_of(cb.from_user), key), show_alert=True)
