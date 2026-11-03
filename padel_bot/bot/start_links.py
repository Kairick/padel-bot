"""Deep links into the private chat: /start parameters made by keyboards.start_link.

Group messages can't show booking links or subscription screens, so their slot and Watch
buttons open the private chat with a /start parameter; this router turns it back into the
screen. It is included first, so the plain /start in browse never sees a known link and
the order of handlers elsewhere doesn't matter.
"""

from datetime import datetime

from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

from padel_bot.bot.browse import cmd_start, slot_view
from padel_bot.bot.common import lang_of, private_router
from padel_bot.bot.i18n import t
from padel_bot.bot.keyboards import (
    SlotCb,
    WatchDayCb,
    is_start_link,
    parse_day,
    parse_start_link,
)
from padel_bot.bot.throttle import RateLimiter
from padel_bot.bot.watch import cmd_watch, hours_view
from padel_bot.domain import TZ, current_play_day
from padel_bot.reservio.service import AvailabilityService
from padel_bot.stats import Stats

start_links_router = private_router("start_links")


@start_links_router.message(CommandStart(deep_link=True, magic=is_start_link(SlotCb)))
async def open_slot_link(
    message: Message,
    command: CommandObject,
    availability: AvailabilityService,
    stats: Stats,
    slot_limiter: RateLimiter,
) -> None:
    """A slot button of a group message: its booking links."""
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


@start_links_router.message(CommandStart(deep_link=True, magic=is_start_link(WatchDayCb)))
async def open_watch_link(message: Message, command: CommandObject) -> None:
    """The Watch button of a group message: the hour grid of its day."""
    data = parse_start_link(command.args, WatchDayCb)
    day = parse_day(data.day, current_play_day()) if data else None
    if data is None or day is None:
        # An old group message (the day has passed) or garbage: pick another day.
        await cmd_watch(message)
        return
    text, markup = hours_view(day, data.rng, lang_of(message.from_user), datetime.now(TZ))
    await message.answer(text, reply_markup=markup)
