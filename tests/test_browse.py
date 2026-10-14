import inspect
from unittest.mock import AsyncMock, MagicMock

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from padel_bot.bot import browse
from padel_bot.bot.i18n import t
from padel_bot.bot.keyboards import DayCb, SlotCb, encode_day
from padel_bot.bot.throttle import RateLimiter
from padel_bot.domain import current_play_day
from padel_bot.reservio.service import Availability


def make_cb(events: list[str]) -> MagicMock:
    cb = MagicMock()
    cb.from_user = MagicMock(id=42, language_code="ru")
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock(side_effect=lambda *a, **k: events.append("edit"))
    cb.answer = AsyncMock(side_effect=lambda *a, **k: events.append("answer"))
    return cb


def make_availability(venues, events: list[str]) -> MagicMock:
    async def get_availability(day, *args, **kwargs):
        events.append("fetch")
        return Availability(day=day, slots=[])

    availability = MagicMock(venues=venues)
    availability.get_availability = AsyncMock(side_effect=get_availability)
    availability.booking_links = AsyncMock(return_value=[])
    return availability


def today() -> str:
    return encode_day(current_play_day())


def slot_cb(day: str, v: int = 0) -> SlotCb:
    return SlotCb(day=day, rng="w", v=v, hm="1800")


async def test_on_slot_answers_before_calling_reservio(venues):
    events: list[str] = []
    cb = make_cb(events)
    availability = make_availability(venues, events)

    await browse.on_slot(cb, slot_cb(today()), availability, MagicMock(), RateLimiter(10, 60))

    assert events[:2] == ["answer", "fetch"]
    text = cb.message.edit_text.await_args.args[0]
    assert text.startswith(t("ru", "slot_taken"))


async def test_on_slot_garbage_day_gets_alert(venues):
    for day in ("garbage", "", "20261345"):
        events: list[str] = []
        cb = make_cb(events)
        availability = make_availability(venues, events)

        await browse.on_slot(cb, slot_cb(day), availability, MagicMock(), RateLimiter(10, 60))

        cb.answer.assert_awaited_once_with(t("ru", "stale_button"), show_alert=True)
        cb.message.edit_text.assert_not_awaited()
        availability.get_availability.assert_not_awaited()


async def test_outdated_day_reopens_day_picker(venues):
    # Yesterday's message after 06:00, or a forged far-future day: no alert, no Reservio calls.
    for day in ("20000101", "20991231"):
        events: list[str] = []
        cb = make_cb(events)
        availability = make_availability(venues, events)

        await browse.on_slot(cb, slot_cb(day), availability, MagicMock(), RateLimiter(10, 60))
        await browse.on_day(
            cb, DayCb(day=day, rng="w"), availability, MagicMock(), RateLimiter(10, 60)
        )

        availability.get_availability.assert_not_awaited()
        assert all(call.args[0] is None for call in cb.answer.await_args_list)
        for call in cb.message.edit_text.await_args_list:
            assert call.args[0] == t("ru", "pick_day")
        assert cb.message.edit_text.await_count == 2


async def test_on_slot_rejects_unknown_venue(venues):
    events: list[str] = []
    cb = make_cb(events)
    availability = make_availability(venues, events)

    await browse.on_slot(cb, slot_cb(today(), v=99), availability, MagicMock(), RateLimiter(10, 60))

    cb.answer.assert_awaited_once_with(t("ru", "stale_button"), show_alert=True)
    availability.get_availability.assert_not_awaited()


async def test_on_slot_rate_limited(venues):
    events: list[str] = []
    cb = make_cb(events)
    availability = make_availability(venues, events)

    await browse.on_slot(cb, slot_cb(today()), availability, MagicMock(), RateLimiter(0, 60))

    cb.answer.assert_awaited_once_with(t("ru", "too_many_requests"), show_alert=True)
    availability.get_availability.assert_not_awaited()
    availability.booking_links.assert_not_awaited()


async def test_on_day_refresh_rate_limited(venues):
    events: list[str] = []
    cb = make_cb(events)
    availability = make_availability(venues, events)
    data = DayCb(day=today(), rng="w", refresh=True)

    await browse.on_day(cb, data, availability, MagicMock(), RateLimiter(0, 60))

    cb.answer.assert_awaited_once_with(t("ru", "too_many_requests"), show_alert=True)
    availability.get_availability.assert_not_awaited()


async def test_on_day_plain_view_is_not_rate_limited(venues):
    events: list[str] = []
    cb = make_cb(events)
    availability = make_availability(venues, events)

    await browse.on_day(
        cb, DayCb(day=today(), rng="w"), availability, MagicMock(), RateLimiter(0, 60)
    )

    availability.get_availability.assert_awaited_once()
    cb.message.edit_text.assert_awaited_once()


async def test_stale_callback_answer_does_not_stop_the_update(venues):
    events: list[str] = []
    cb = make_cb(events)
    cb.answer.side_effect = TelegramBadRequest(method=MagicMock(), message="query is too old")
    availability = make_availability(venues, events)

    await browse.on_day(
        cb, DayCb(day=today(), rng="w"), availability, MagicMock(), RateLimiter(10, 60)
    )

    availability.get_availability.assert_awaited_once()
    cb.message.edit_text.assert_awaited_once()


def make_message(chat_type: str) -> Message:
    return Message.model_validate(
        {
            "message_id": 1,
            "date": 0,
            "chat": {"id": 1, "type": chat_type},
            "from": {"id": 1, "is_bot": False, "first_name": "Test"},
            "text": "/start",
        }
    )


async def passes(observer, event) -> bool:
    result = observer.check_root_filters(event)
    if inspect.isawaitable(result):
        result = await result
    return bool(result[0])


async def test_main_router_works_only_in_private_chats():
    assert await passes(browse.browse_router.message, make_message("private"))
    for chat_type in ("group", "supergroup", "channel"):
        assert not await passes(browse.browse_router.message, make_message(chat_type))
        assert await passes(browse.group_router.message, make_message(chat_type))
    assert not await passes(browse.group_router.message, make_message("private"))


async def test_group_command_points_to_private_chat():
    message = MagicMock(from_user=MagicMock(language_code="en"))
    message.answer = AsyncMock()
    bot = MagicMock()
    bot.me = AsyncMock(return_value=MagicMock(username="batumipadel_bot"))

    await browse.on_group_command(message, bot)

    text = message.answer.await_args.args[0]
    assert "https://t.me/batumipadel_bot" in text
