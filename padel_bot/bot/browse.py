from datetime import timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from padel_bot.bot.common import (
    answer_quietly,
    build_day_view,
    lang_of,
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
    days_keyboard,
    normalize_range,
    slot_keyboard,
)
from padel_bot.bot.throttle import RateLimiter
from padel_bot.domain import current_play_day
from padel_bot.reservio.service import AvailabilityService
from padel_bot.stats import Stats, format_summary

browse_router = private_router("private")

# Included after `router`: group commands, plus every callback the private router rejected
# (groups, forwarded copies, inaccessible or inline messages), so no tap stays unanswered.
group_router = Router(name="fallback")
group_router.message.filter(F.chat.type != ChatType.PRIVATE)


@browse_router.message(CommandStart())
@browse_router.message(Command("days"))
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


@browse_router.message(Command("today"))
async def cmd_today(message: Message, availability: AvailabilityService, stats: Stats) -> None:
    lang = lang_of(message.from_user)
    stats.track_event("day_view")
    text, markup = await build_day_view(availability, current_play_day(), DEFAULT_RANGE, lang)
    await message.answer(text, reply_markup=markup)


@browse_router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message, availability: AvailabilityService, stats: Stats) -> None:
    lang = lang_of(message.from_user)
    stats.track_event("day_view")
    day = current_play_day() + timedelta(days=1)
    text, markup = await build_day_view(availability, day, DEFAULT_RANGE, lang)
    await message.answer(text, reply_markup=markup)


@browse_router.callback_query(F.data == NOOP)
async def on_noop(cb: CallbackQuery) -> None:
    await answer_quietly(cb)


@browse_router.callback_query(F.data == DAYS)
async def on_days(cb: CallbackQuery) -> None:
    await answer_quietly(cb)
    lang = lang_of(cb.from_user)
    if isinstance(cb.message, Message):
        await safe_edit(cb.message, t(lang, "pick_day"), days_keyboard(current_play_day(), lang))


@browse_router.callback_query(DayCb.filter())
async def on_day(
    cb: CallbackQuery,
    callback_data: DayCb,
    availability: AvailabilityService,
    stats: Stats,
    refresh_limiter: RateLimiter,
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
    text, markup = await build_day_view(availability, day, callback_data.rng, lang, refresh=refresh)
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
        await safe_edit(message, f"{notice}\n\n{text}", markup)
        return
    stats.track_event("slot_view", venue=venue.key, hour=slots[0].start.hour)
    links = await availability.booking_links(slots, user_id=cb.from_user.id)
    await safe_edit(
        message,
        render_slot(venue, day, slots[0].start, slots, lang),
        slot_keyboard(list(zip(slots, links, strict=True)), day, rng, lang),
    )


# Not /stats: it's for admins, a group doesn't need to learn it exists.
@group_router.message(Command("start", "days", "today", "tomorrow", "watch", "subs", "feedback"))
async def on_group_command(message: Message, bot: Bot) -> None:
    me = await bot.me()
    link = f"https://t.me/{me.username}"
    await message.answer(t(lang_of(message.from_user), "private_only", link=link))


@group_router.callback_query()
async def on_foreign_callback(cb: CallbackQuery) -> None:
    in_group = cb.message is not None and cb.message.chat.type != ChatType.PRIVATE
    key = "private_only_short" if in_group else "stale_button"
    await answer_quietly(cb, t(lang_of(cb.from_user), key), show_alert=True)
