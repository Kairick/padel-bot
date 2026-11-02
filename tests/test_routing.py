import inspect
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import CallbackQuery, Message

from padel_bot.bot import browse
from padel_bot.bot.i18n import t
from padel_bot.bot.keyboards import SlotCb, encode_day
from padel_bot.bot.throttle import RateLimiter
from padel_bot.domain import current_play_day
from padel_bot.reservio.service import Availability

MESSAGE_DATE = 1_789_000_000
# What Telegram sends for a message the bot can no longer access: no sender, no text, date 0.
INACCESSIBLE = {"message_id": 1, "date": 0, "chat": {"id": 7, "type": "private"}}


def message(chat_type: str, from_bot: bool, date: int = MESSAGE_DATE) -> dict:
    sender = (
        {"id": 99, "is_bot": True, "first_name": "Bot"}
        if from_bot
        else {
            "id": 8,
            "is_bot": False,
            "first_name": "Friend",
        }
    )
    return {
        "message_id": 1,
        "date": date,
        "chat": {"id": 7, "type": chat_type},
        "from": sender,
        "text": "x",
    }


def callback(msg: dict | None) -> CallbackQuery:
    data = {
        "id": "1",
        "from": {"id": 7, "is_bot": False, "first_name": "User", "language_code": "ru"},
        "chat_instance": "c",
        "data": "noop",
    }
    if msg is None:
        data["inline_message_id"] = "inline"
    else:
        data["message"] = msg
    return CallbackQuery.model_validate(data)


async def passes(observer, event) -> bool:
    result = observer.check_root_filters(event)
    if inspect.isawaitable(result):
        result = await result
    return bool(result[0])


async def test_private_router_takes_only_own_messages_in_private_chats():
    private = browse.browse_router.callback_query
    assert await passes(private, callback(message("private", from_bot=True)))
    assert not await passes(private, callback(message("private", from_bot=False)))  # forwarded
    assert not await passes(private, callback(message("group", from_bot=True)))
    assert not await passes(private, callback(INACCESSIBLE))
    assert not await passes(private, callback(None))  # inline message


async def test_fallback_router_catches_every_rejected_callback():
    fallback = browse.fallback_router.callback_query
    for cb in (
        callback(message("private", from_bot=False)),
        callback(message("group", from_bot=True)),
        callback(INACCESSIBLE),
        callback(None),
    ):
        assert await passes(fallback, cb)


async def test_foreign_callback_answers():
    cases = [
        (MagicMock(chat=MagicMock(type="group")), "private_only_short"),
        (MagicMock(chat=MagicMock(type="private")), "stale_button"),  # forwarded copy
        (None, "stale_button"),
    ]
    for msg, key in cases:
        cb = MagicMock(from_user=MagicMock(language_code="ru"), message=msg)
        cb.answer = AsyncMock()

        await browse.on_foreign_callback(cb)

        cb.answer.assert_awaited_once_with(t("ru", key), show_alert=True)


async def test_on_slot_reports_failed_venue_instead_of_taken_slot(venues):
    day = current_play_day()
    cb = MagicMock(from_user=MagicMock(id=1, language_code="ru"))
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    availability = MagicMock(venues=venues)
    availability.get_availability = AsyncMock(
        return_value=Availability(day=day, slots=[], failed_venues=[venues[0]])
    )
    data = SlotCb(day=encode_day(day), rng="w", v=0, hm="1800")

    await browse.on_slot(cb, data, availability, MagicMock(), RateLimiter(10, 60))

    text = cb.message.edit_text.await_args.args[0]
    assert text.startswith(f"⚠️ {venues[0].name}: {t('ru', 'venue_failed')}")
    assert t("ru", "slot_taken") not in text


async def test_group_router_takes_only_own_messages_in_groups():
    group = browse.group_browse_router.callback_query
    for chat_type in ("group", "supergroup"):
        assert await passes(group, callback(message(chat_type, from_bot=True)))
        assert not await passes(group, callback(message(chat_type, from_bot=False)))
    assert not await passes(group, callback(message("private", from_bot=True)))
    assert not await passes(group, callback(INACCESSIBLE))
    assert not await passes(group, callback(None))


async def test_group_slot_tap_is_never_handled_as_a_booking():
    # Slot buttons in groups are links; a forged SlotCb from a group falls to the fallback.
    cb = callback(message("group", from_bot=True))
    cb = cb.model_copy(update={"data": SlotCb(day="20260915", rng="w", v=0, hm="1800").pack()})
    assert not await passes(browse.browse_router.callback_query, cb)
    for handler in browse.group_browse_router.callback_query.handlers:
        assert not (await handler.check(cb))[0]
    assert await passes(browse.fallback_router.callback_query, cb)
