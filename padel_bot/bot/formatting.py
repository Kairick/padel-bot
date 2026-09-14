from datetime import date, datetime
from decimal import Decimal
from html import escape
from itertools import groupby

from padel_bot.reservio.models import CourtSlot, Venue
from padel_bot.reservio.service import Availability

WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WEEKDAYS_FULL = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]  # fmt: skip


def day_button_label(day: date, today: date) -> str:
    delta = (day - today).days
    if delta == 0:
        return "Сегодня"
    if delta == 1:
        return "Завтра"
    return f"{WEEKDAYS_SHORT[day.weekday()]} {day:%d.%m}"


def day_title(day: date) -> str:
    return f"{WEEKDAYS_FULL[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}"


def fmt_price(prices: set[Decimal]) -> str:
    values = sorted(prices)
    lo, hi = f"{values[0].normalize():f}", f"{values[-1].normalize():f}"
    return f"{lo} ₾" if lo == hi else f"{lo}–{hi} ₾"


def group_by_start(slots: list[CourtSlot]) -> list[tuple[datetime, list[CourtSlot]]]:
    ordered = sorted(slots, key=lambda s: (s.start, s.court.name))
    return [(start, list(items)) for start, items in groupby(ordered, key=lambda s: s.start)]


def render_day(availability: Availability, venues: list[Venue], range_label: str) -> str:
    """Only the day header: slots themselves are shown as buttons."""
    lines = [f"📅 <b>{day_title(availability.day)}</b> · {escape(range_label)}"]
    by_venue = availability.by_venue()
    failed = {v.key for v in availability.failed_venues}

    for venue in venues:
        has_slots = bool(by_venue.get(venue.key))
        if venue.key in failed:
            status = "часть кортов не ответила" if has_slots else "не удалось получить расписание"
            lines.append(f"⚠️ {escape(venue.name)}: {status}")
        elif not has_slots:
            lines.append(f"<i>{escape(venue.name)}: свободных слотов нет</i>")
    return "\n".join(lines)


def render_slot(venue: Venue, day: date, start: datetime, slots: list[CourtSlot]) -> str:
    end = max(s.end for s in slots)
    lines = [
        f"🎾 <b>{escape(venue.name)}</b>",
        f"📅 {day_title(day)} · <b>{start:%H:%M}–{end:%H:%M}</b>",
        "",
        "Свободные корты:",
    ]
    for s in sorted(slots, key=lambda s: s.court.name):
        group = f" <i>({escape(s.court.group)})</i>" if s.court.group else ""
        lines.append(f"• {escape(s.court.name)}{group} · {fmt_price({s.price})}")
    lines += [
        "",
        f"Кнопка откроет страницу брони корта. Там выбери дату и время <b>{start:%H:%M}</b>.",
    ]
    return "\n".join(lines)
