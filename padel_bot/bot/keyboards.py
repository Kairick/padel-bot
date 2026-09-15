from datetime import date, datetime, timedelta

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from padel_bot.bot.formatting import day_button_label, fmt_price, group_by_start
from padel_bot.bot.i18n import Lang, t
from padel_bot.reservio.models import CourtSlot, Venue
from padel_bot.reservio.service import WHOLE_DAY, Availability, TimeRange

BOOKING_WINDOW_DAYS = 7
NOOP = "noop"
DAYS = "days"

# Labels live in i18n under "range_<key>" and "range_btn_<key>".
RANGES: dict[str, TimeRange] = {
    "m": TimeRange(6, 13),
    "a": TimeRange(13, 17),
    "e": TimeRange(17, 30),
    "w": WHOLE_DAY,
}
DEFAULT_RANGE = "w"


class DayCb(CallbackData, prefix="d"):
    day: str  # YYYYMMDD
    rng: str
    refresh: bool = False


class SlotCb(CallbackData, prefix="s"):
    day: str
    rng: str
    v: int  # venue index
    hm: str  # HHMM of slot start


def normalize_range(rng: str) -> str:
    return rng if rng in RANGES else DEFAULT_RANGE


def encode_day(day: date) -> str:
    return f"{day:%Y%m%d}"


def decode_day(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def try_decode_day(value: str) -> date | None:
    try:
        return decode_day(value)
    except ValueError:
        return None


def parse_day(value: str, today: date) -> date | None:
    """Day from callback data, or None if it is malformed or outside the booking window.

    Callback data comes from the client and can be forged, so it is never trusted as is.
    """
    day = try_decode_day(value)
    if day is None:
        return None
    return day if today <= day < today + timedelta(days=BOOKING_WINDOW_DAYS) else None


def days_keyboard(today: date, lang: Lang, rng: str = DEFAULT_RANGE) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i in range(BOOKING_WINDOW_DAYS):
        day = today + timedelta(days=i)
        kb.button(
            text=day_button_label(day, today, lang),
            callback_data=DayCb(day=encode_day(day), rng=rng),
        )
    kb.adjust(2, 3, 2)
    return kb.as_markup()


def day_keyboard(
    availability: Availability, venues: list[Venue], rng: str, lang: Lang
) -> InlineKeyboardMarkup:
    day = encode_day(availability.day)
    rows: list[list[InlineKeyboardButton]] = []

    rows.append(
        [
            InlineKeyboardButton(
                text=("✓ " if key == rng else "") + t(lang, f"range_btn_{key}"),
                callback_data=DayCb(day=day, rng=key).pack(),
            )
            for key in RANGES
        ]
    )

    by_venue = availability.by_venue()
    for idx, venue in enumerate(venues):
        groups = group_by_start(by_venue.get(venue.key, []))
        if not groups:
            continue
        rows.append([InlineKeyboardButton(text=f"— {venue.name} —", callback_data=NOOP)])
        buttons = [
            InlineKeyboardButton(
                text=f"{start:%H:%M} ({len(items)})",
                callback_data=SlotCb(day=day, rng=rng, v=idx, hm=f"{start:%H%M}").pack(),
            )
            for start, items in groups
        ]
        rows += [buttons[i : i + 4] for i in range(0, len(buttons), 4)]

    rows.append(
        [
            InlineKeyboardButton(text=t(lang, "other_day"), callback_data=DAYS),
            InlineKeyboardButton(
                text=t(lang, "refresh"),
                callback_data=DayCb(day=day, rng=rng, refresh=True).pack(),
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def slot_keyboard(
    links: list[tuple[CourtSlot, str]], day: date, rng: str, lang: Lang
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s, url in links:
        kb.button(text=f"{s.court.name} · {fmt_price({s.price})}", url=url)
    kb.adjust(2)
    kb.row(
        InlineKeyboardButton(
            text=t(lang, "back"), callback_data=DayCb(day=encode_day(day), rng=rng).pack()
        )
    )
    return kb.as_markup()
