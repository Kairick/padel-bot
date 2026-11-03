"""Helpers shared by the chat handlers: routing, language, message edits, day view."""

import logging
from datetime import date

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, User

from padel_bot.bot.formatting import render_day
from padel_bot.bot.i18n import t
from padel_bot.bot.keyboards import (
    RANGES,
    day_keyboard,
    days_keyboard,
    normalize_range,
    parse_day,
    try_decode_day,
)
from padel_bot.domain import Lang, current_play_day, detect_lang
from padel_bot.reservio.service import AvailabilityService

log = logging.getLogger(__name__)


def private_router(name: str) -> Router:
    """Router for private chats and the bot's own messages only.

    Booking links are Reservio draft orders: anyone who sees the message can open them.
    A forwarded copy of a bot message in someone else's chat can't be edited and must not
    create orders or touch subscriptions.
    """
    router = Router(name=name)
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.callback_query.filter(
        F.message.chat.type == ChatType.PRIVATE,
        F.message.from_user.is_bot,
    )
    return router


def group_router(name: str) -> Router:
    """Router for group chats: browsing only, on the bot's own messages.

    Slot and Watch taps in groups are answered with a link to the private chat, so nothing
    here creates booking orders or touches subscriptions.
    """
    router = Router(name=name)
    router.message.filter(F.chat.type != ChatType.PRIVATE)
    router.callback_query.filter(
        F.message.chat.type != ChatType.PRIVATE,
        F.message.from_user.is_bot,
    )
    return router


def lang_of(user: User | None) -> Lang:
    """Get the language code of the user."""
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
    availability: AvailabilityService,
    day: date,
    rng: str,
    lang: Lang,
    refresh: bool = False,
) -> tuple[str, InlineKeyboardMarkup]:
    rng = normalize_range(rng)
    result = await availability.get_availability(day, RANGES[rng], force_refresh=refresh)
    text = render_day(result, availability.venues, rng, lang)
    return text, day_keyboard(result, availability.venues, rng, lang)


async def safe_edit(message: Message, text: str, markup: InlineKeyboardMarkup) -> None:
    """Safely edit a message."""
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def resolve_day(cb: CallbackQuery, value: str, lang: Lang) -> tuple[Message, date] | None:
    """Message and day of a day button if it can be shown; otherwise handle the tap, return None.

    An inaccessible message or garbage gets an alert. A well-formed day outside the booking
    window (typically yesterday's message after 06:00) reopens the day picker, so the
    message stays usable.
    """
    message = cb.message
    if not isinstance(message, Message):
        await answer_quietly(cb, t(lang, "stale_button"), show_alert=True)
        return None
    today = current_play_day()
    day = parse_day(value, today)
    if day is not None:
        return message, day
    if try_decode_day(value) is None:
        await answer_quietly(cb, t(lang, "stale_button"), show_alert=True)
    else:
        await answer_quietly(cb)
        await safe_edit(message, t(lang, "pick_day"), days_keyboard(today, lang))
    return None
