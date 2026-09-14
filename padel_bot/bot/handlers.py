import logging
from contextlib import suppress
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from padel_bot.bot.formatting import render_day, render_slot
from padel_bot.bot.keyboards import (
    DAYS,
    NOOP,
    RANGES,
    DayCb,
    SlotCb,
    day_keyboard,
    days_keyboard,
    decode_day,
    slot_keyboard,
)
from padel_bot.reservio.service import AvailabilityService, current_play_day

log = logging.getLogger(__name__)
router = Router()

WELCOME = (
    "Привет! Я показываю свободные корты для падела в Батуми "
    "(Padel Port и Grand Padel) и даю ссылку на бронь.\n\n"
    "Выбери день 👇"
)


async def build_day_view(
    availability: AvailabilityService, day: date, rng: str, refresh: bool = False
) -> tuple[str, InlineKeyboardMarkup]:
    label, time_range = RANGES.get(rng, RANGES["w"])
    result = await availability.get_availability(day, time_range, force_refresh=refresh)
    text = render_day(result, availability.venues, label)
    return text, day_keyboard(result, availability.venues, rng)


async def safe_edit(message: Message, text: str, markup: InlineKeyboardMarkup) -> None:
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


@router.message(CommandStart())
@router.message(Command("days"))
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME, reply_markup=days_keyboard(current_play_day()))


@router.message(Command("today"))
async def cmd_today(message: Message, availability: AvailabilityService) -> None:
    text, markup = await build_day_view(availability, current_play_day(), "w")
    await message.answer(text, reply_markup=markup)


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message, availability: AvailabilityService) -> None:
    text, markup = await build_day_view(availability, current_play_day() + timedelta(days=1), "w")
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == NOOP)
async def on_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(F.data == DAYS)
async def on_days(cb: CallbackQuery) -> None:
    await cb.answer()
    if isinstance(cb.message, Message):
        await safe_edit(cb.message, "Выбери день 👇", days_keyboard(current_play_day()))


@router.callback_query(DayCb.filter())
async def on_day(
    cb: CallbackQuery, callback_data: DayCb, availability: AvailabilityService
) -> None:
    await cb.answer("Обновляю…" if callback_data.refresh else None)
    if not isinstance(cb.message, Message):
        return
    day = decode_day(callback_data.day)
    text, markup = await build_day_view(
        availability, day, callback_data.rng, refresh=callback_data.refresh
    )
    await safe_edit(cb.message, text, markup)


@router.callback_query(SlotCb.filter())
async def on_slot(
    cb: CallbackQuery, callback_data: SlotCb, availability: AvailabilityService
) -> None:
    if not isinstance(cb.message, Message):
        return await cb.answer()
    day = decode_day(callback_data.day)
    venues = availability.venues
    if not 0 <= callback_data.v < len(venues):
        return await cb.answer("Устаревшая кнопка", show_alert=True)
    venue = venues[callback_data.v]
    _, time_range = RANGES.get(callback_data.rng, RANGES["w"])
    result = await availability.get_availability(day, time_range)
    slots = [
        s for s in result.by_venue().get(venue.key, []) if f"{s.start:%H%M}" == callback_data.hm
    ]
    if not slots:
        await cb.answer("Этот слот уже заняли 😕", show_alert=True)
        text, markup = await build_day_view(availability, day, callback_data.rng)
        with suppress(TelegramBadRequest):
            await cb.message.edit_text(text, reply_markup=markup)
        return
    await cb.answer()
    await safe_edit(
        cb.message,
        render_slot(venue, day, slots[0].start, slots),
        slot_keyboard(slots, day, callback_data.rng),
    )
