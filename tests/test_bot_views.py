from datetime import date

import pytest

from padel_bot.bot.formatting import render_day, render_slot
from padel_bot.bot.i18n import t
from padel_bot.bot.keyboards import WatchDayCb, day_keyboard, days_keyboard, slot_keyboard
from padel_bot.reservio.service import AvailabilityService
from tests.conftest import FakeClient, dt, slot

DAY = date(2026, 9, 15)


async def make_result(venues):
    client = FakeClient(
        {
            "pp1": [slot("2026-09-15T18:00:00")],
            "pp2": [slot("2026-09-15T18:00:00"), slot("2026-09-16T00:00:00")],
        },
        failing={"gpa-day"},
    )
    svc = AvailabilityService(client, venues)
    return await svc.get_availability(DAY, now=dt("2026-09-15T09:00:00"))


async def test_render_day_ru(venues):
    result = await make_result(venues)
    text = render_day(result, venues, "w", "ru")
    assert text.splitlines()[0] == "📅 <b>Вторник, 15 сентября</b> · Весь день"
    assert "18:00" not in text
    assert "⚠️ Grand Padel: не удалось получить расписание" in text
    assert "Padel Port" not in text


async def test_render_day_en(venues):
    result = await make_result(venues)
    text = render_day(result, venues, "e", "en")
    assert text.splitlines()[0] == "📅 <b>Tuesday, 15 September</b> · Evening"
    assert "⚠️ Grand Padel: couldn't load the schedule" in text


@pytest.mark.parametrize("lang", ["ru", "en"])
async def test_keyboards_callback_data_fits_telegram_limit(venues, lang):
    result = await make_result(venues)
    markups = [
        day_keyboard(result, venues, "w", lang),
        days_keyboard(DAY, lang),
        slot_keyboard([(s, s.booking_url) for s in result.slots], DAY, "w", lang),
    ]
    buttons = [b for m in markups for row in m.inline_keyboard for b in row]
    assert all(len(b.callback_data.encode()) <= 64 for b in buttons if b.callback_data)
    slot_buttons = list(markups[0].inline_keyboard[2])
    assert [b.text for b in slot_buttons] == ["18:00 (2)", "00:00 (1)"]
    assert any(b.url and "booking?step=2" in b.url for b in buttons)
    watch_row = markups[0].inline_keyboard[-2]
    assert [b.text for b in watch_row] == [t(lang, "watch_btn")]
    assert watch_row[0].callback_data == WatchDayCb(day="20260915", rng="w").pack()


async def test_render_slot(venues):
    result = await make_result(venues)
    slots = [s for s in result.slots if s.start.hour == 18]
    ru = render_slot(venues[0], DAY, slots[0].start, slots, "ru")
    assert "18:00–18:59" in ru
    assert "• Padel 1 · 80 ₾" in ru
    assert "бронь на <b>18:00</b>" in ru
    assert "Continue" in ru
    en = render_slot(venues[0], DAY, slots[0].start, slots, "en")
    assert "Free courts:" in en
    assert "booking for <b>18:00</b>" in en


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("ru", ["Утро", "День", "Вечер", "✓ Все"]),
        ("en", ["Morning", "Day", "Evening", "✓ All"]),
    ],
)
async def test_range_buttons_are_short(venues, lang, expected):
    result = await make_result(venues)
    row = day_keyboard(result, venues, "w", lang).inline_keyboard[0]
    assert [b.text for b in row] == expected


def test_days_keyboard_labels():
    ru = [b.text for row in days_keyboard(DAY, "ru").inline_keyboard for b in row]
    en = [b.text for row in days_keyboard(DAY, "en").inline_keyboard for b in row]
    assert ru[:3] == ["Сегодня", "Завтра", "чт 17.09"]
    assert en[:3] == ["Today", "Tomorrow", "Thu 17.09"]


async def test_group_day_keyboard_links_private_screens_to_the_bot(venues):
    result = await make_result(venues)
    markup = day_keyboard(result, venues, "w", "ru", bot_username="padel_bot")
    rows = markup.inline_keyboard

    slot_buttons = rows[2]
    assert [b.text for b in slot_buttons] == ["18:00 (2)", "00:00 (1)"]
    assert slot_buttons[0].callback_data is None
    assert slot_buttons[0].url == "https://t.me/padel_bot?start=s_20260915_w_0_1800"
    watch_button = rows[-2][0]
    assert watch_button.url == "https://t.me/padel_bot?start=wh_20260915_w"
    # Browsing stays in the group: ranges, other day, refresh.
    assert all(b.callback_data for b in rows[0] + rows[-1])
