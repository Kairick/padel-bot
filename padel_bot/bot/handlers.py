import logging
from contextlib import suppress
from datetime import date, timedelta

from aiogram import F, Router
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
    decode_day,
    normalize_range,
    slot_keyboard,
)
from padel_bot.reservio.service import AvailabilityService, current_play_day

log = logging.getLogger(__name__)
router = Router()


def lang_of(user: User | None) -> Lang:
    return detect_lang(user.language_code if user else None)


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


@router.message(CommandStart())
@router.message(Command("days"))
async def cmd_start(message: Message) -> None:
    lang = lang_of(message.from_user)
    await message.answer(t(lang, "welcome"), reply_markup=days_keyboard(current_play_day(), lang))


@router.message(Command("today"))
async def cmd_today(message: Message, availability: AvailabilityService) -> None:
    lang = lang_of(message.from_user)
    text, markup = await build_day_view(availability, current_play_day(), DEFAULT_RANGE, lang)
    await message.answer(text, reply_markup=markup)


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message, availability: AvailabilityService) -> None:
    lang = lang_of(message.from_user)
    day = current_play_day() + timedelta(days=1)
    text, markup = await build_day_view(availability, day, DEFAULT_RANGE, lang)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == NOOP)
async def on_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(F.data == DAYS)
async def on_days(cb: CallbackQuery) -> None:
    await cb.answer()
    lang = lang_of(cb.from_user)
    if isinstance(cb.message, Message):
        await safe_edit(cb.message, t(lang, "pick_day"), days_keyboard(current_play_day(), lang))


@router.callback_query(DayCb.filter())
async def on_day(
    cb: CallbackQuery, callback_data: DayCb, availability: AvailabilityService
) -> None:
    lang = lang_of(cb.from_user)
    await cb.answer(t(lang, "refreshing") if callback_data.refresh else None)
    if not isinstance(cb.message, Message):
        return
    day = decode_day(callback_data.day)
    text, markup = await build_day_view(
        availability, day, callback_data.rng, lang, refresh=callback_data.refresh
    )
    await safe_edit(cb.message, text, markup)


@router.callback_query(SlotCb.filter())
async def on_slot(
    cb: CallbackQuery, callback_data: SlotCb, availability: AvailabilityService
) -> None:
    lang = lang_of(cb.from_user)
    if not isinstance(cb.message, Message):
        return await cb.answer()
    day = decode_day(callback_data.day)
    rng = normalize_range(callback_data.rng)
    venues = availability.venues
    if not 0 <= callback_data.v < len(venues):
        return await cb.answer(t(lang, "stale_button"), show_alert=True)
    venue = venues[callback_data.v]
    result = await availability.get_availability(day, RANGES[rng])
    slots = sorted(
        (s for s in result.by_venue().get(venue.key, []) if f"{s.start:%H%M}" == callback_data.hm),
        key=lambda s: s.court.name,
    )
    if not slots:
        await cb.answer(t(lang, "slot_taken"), show_alert=True)
        text, markup = await build_day_view(availability, day, rng, lang)
        with suppress(TelegramBadRequest):
            await cb.message.edit_text(text, reply_markup=markup)
        return
    await cb.answer()
    links = await availability.booking_links(slots)
    await safe_edit(
        cb.message,
        render_slot(venue, day, slots[0].start, slots, lang),
        slot_keyboard(list(zip(slots, links, strict=True)), day, rng, lang),
    )
