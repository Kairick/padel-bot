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

MAX_MESSAGE_LEN = 4000


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
    lines = [f"📅 <b>{day_title(availability.day)}</b> · {escape(range_label)}", ""]
    by_venue = availability.by_venue()
    failed = {v.key for v in availability.failed_venues}

    for venue in venues:
        lines.append(f"🎾 <b>{escape(venue.name)}</b>")
        slots = by_venue.get(venue.key, [])
        if venue.key in failed and not slots:
            lines.append("⚠️ не удалось получить расписание")
        elif not slots:
            lines.append("<i>свободных слотов нет</i>")
        for start, items in group_by_start(slots):
            courts = ", ".join(escape(s.court.name) for s in items)
            price = fmt_price({s.price for s in items})
            lines.append(f"<code>{start:%H:%M}</code>  {courts} · {price}")
        if venue.key in failed and slots:
            lines.append("⚠️ часть кортов не ответила")
        lines.append("")

    lines.append("Нажми на время, чтобы получить ссылку на бронь 👇")
    text = "\n".join(lines)
    if len(text) > MAX_MESSAGE_LEN:
        text = text[: MAX_MESSAGE_LEN - 20].rsplit("\n", 1)[0] + "\n…"
    return text


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
