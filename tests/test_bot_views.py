from datetime import date

from padel_bot.bot.formatting import render_day, render_slot
from padel_bot.bot.keyboards import day_keyboard, days_keyboard, slot_keyboard
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


async def test_render_day(venues):
    result = await make_result(venues)
    text = render_day(result, venues, "Весь день")
    assert text.splitlines()[0] == "📅 <b>Вторник, 15 сентября</b> · Весь день"
    assert "18:00" not in text
    assert "⚠️ Grand Padel: не удалось получить расписание" in text
    assert "Padel Port" not in text


async def test_keyboards_callback_data_fits_telegram_limit(venues):
    result = await make_result(venues)
    markups = [
        day_keyboard(result, venues, "w"),
        days_keyboard(DAY),
        slot_keyboard(result.slots, DAY, "w"),
    ]
    buttons = [b for m in markups for row in m.inline_keyboard for b in row]
    assert all(len(b.callback_data.encode()) <= 64 for b in buttons if b.callback_data)
    slot_buttons = [b for b in markups[0].inline_keyboard[2]]
    assert [b.text for b in slot_buttons] == ["18:00 (2)", "00:00 (1)"]
    assert any(b.url and "booking?step=2" in b.url for b in buttons)


async def test_render_slot(venues):
    result = await make_result(venues)
    slots = [s for s in result.slots if s.start.hour == 18]
    text = render_slot(venues[0], DAY, slots[0].start, slots)
    assert "18:00–18:59" in text
    assert "• Padel 1 · 80 ₾" in text


async def test_range_buttons_are_short(venues):
    result = await make_result(venues)
    row = day_keyboard(result, venues, "w").inline_keyboard[0]
    assert [b.text for b in row] == ["Утро", "День", "Вечер", "✓ Все"]
