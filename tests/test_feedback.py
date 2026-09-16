import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import CommandObject
from aiogram.methods import ForwardMessage, SendMessage, TelegramMethod
from aiogram.types import Message, Update, User

from padel_bot.bot import feedback, handlers, watch
from padel_bot.bot.i18n import t
from padel_bot.bot.throttle import RateLimiter
from padel_bot.reservio.service import Availability

ADMINS = frozenset({1})


def make_message(
    text: str | None = "не работает",
    photo: bool = False,
    message_id: int = 7,
    album: str | None = None,
    caption: str | None = None,
) -> Message:
    data = {
        "message_id": message_id,
        "date": 0,
        "chat": {"id": 42, "type": "private"},
        "from": {
            "id": 42,
            "is_bot": False,
            "first_name": "Иван",
            "username": "ivan_p",
            "language_code": "ru",
        },
        "text": text,
        "caption": caption,
    }
    if photo:
        data["photo"] = [{"file_id": "f", "file_unique_id": "u", "width": 1, "height": 1}]
    if album:
        data["media_group_id"] = album
    return Message.model_validate(data)


def photo(message_id: int, album: str | None = None, caption: str | None = None) -> Message:
    return make_message(None, photo=True, message_id=message_id, album=album, caption=caption)


def bound_bot() -> AsyncMock:
    # message.answer() awaits bot(SendMessage), so every answer lands in bot.call_args_list.
    bot = AsyncMock()
    bot.forward_message.return_value = MagicMock(message_id=100)
    return bot


def answered(bot: AsyncMock) -> list[str]:
    return [call.args[0].text for call in bot.call_args_list]


def forwarded(bot: AsyncMock) -> list[int]:
    return [call.args[2] for call in bot.forward_message.await_args_list]


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    feedback.waiting.clear()
    feedback.albums.clear()
    monkeypatch.setattr(feedback, "ALBUM_GRACE_SECONDS", 0.05)
    yield
    feedback.waiting.clear()
    feedback.albums.clear()


async def command(bot, message, admins=ADMINS, limiter=None, stats=None):
    text = message.text or message.caption or ""
    args = text.partition(" ")[2] or None
    await feedback.cmd_feedback(
        message.as_(bot),
        CommandObject(command="feedback", args=args),
        bot,
        admins,
        stats or MagicMock(),
        limiter or RateLimiter(5, 60),
    )


async def plain(bot, message, admins=ADMINS, limiter=None, stats=None):
    await feedback.on_message(
        message.as_(bot), bot, admins, stats or MagicMock(), limiter or RateLimiter(5, 60)
    )


async def test_inline_feedback_is_forwarded_with_sender():
    bot = bound_bot()
    stats = MagicMock()

    await command(bot, make_message("/feedback нет Лужников"), stats=stats)

    bot.forward_message.assert_awaited_once_with(1, 42, 7)
    info = bot.send_message.await_args
    assert info.args[0] == 1
    assert "<code>42</code>" in info.args[1] and "@ivan_p" in info.args[1]
    assert info.kwargs["reply_parameters"].message_id == 100
    stats.track_event.assert_called_once_with("feedback")
    assert answered(bot) == [t("ru", "feedback_thanks")]


async def test_bare_command_waits_for_one_next_message():
    bot = bound_bot()
    await command(bot, make_message("/feedback"))

    assert answered(bot) == [t("ru", "feedback_prompt")]
    bot.forward_message.assert_not_awaited()

    await plain(bot, photo(8))
    await plain(bot, make_message("ещё текст", message_id=9))

    assert forwarded(bot) == [8]
    assert answered(bot)[-1] == t("ru", "feedback_thanks")


async def test_plain_message_without_wait_is_ignored():
    bot = bound_bot()

    await plain(bot, make_message())

    bot.forward_message.assert_not_awaited()
    assert answered(bot) == []


async def test_captioned_screenshot_is_the_feedback():
    bot = bound_bot()

    await command(bot, photo(7, caption="/feedback"))

    assert forwarded(bot) == [7]
    assert answered(bot) == [t("ru", "feedback_thanks")]
    assert 42 not in feedback.waiting


async def test_rate_limited():
    bot = bound_bot()
    stats = MagicMock()

    await command(bot, make_message("/feedback спам"), limiter=RateLimiter(0, 60), stats=stats)

    bot.forward_message.assert_not_awaited()
    stats.track_event.assert_not_called()
    assert answered(bot) == [t("ru", "feedback_too_many")]


async def test_one_unreachable_admin_does_not_block_others():
    bot = bound_bot()
    bot.forward_message.side_effect = [
        TelegramForbiddenError(method=MagicMock(), message="bot can't initiate conversation"),
        MagicMock(message_id=100),
    ]

    # Small ints iterate in order, so admin 1 is the unreachable one.
    await command(bot, make_message("/feedback x"), admins=frozenset({1, 2}))

    assert bot.send_message.await_count == 1
    assert answered(bot) == [t("ru", "feedback_thanks")]


async def test_sender_line_failure_still_counts_as_delivered():
    bot = bound_bot()
    bot.send_message.side_effect = TelegramForbiddenError(method=MagicMock(), message="no")

    await command(bot, make_message("/feedback x"))

    assert answered(bot) == [t("ru", "feedback_thanks")]


async def test_no_admins_answers_without_waiting():
    bot = bound_bot()

    await command(bot, make_message("/feedback"), admins=frozenset())

    assert answered(bot) == [t("ru", "feedback_failed")]
    assert 42 not in feedback.waiting


async def test_not_delivered_tells_user():
    bot = bound_bot()
    bot.forward_message.side_effect = TelegramForbiddenError(method=MagicMock(), message="no")
    stats = MagicMock()

    await command(bot, make_message("/feedback x"), stats=stats)

    stats.track_event.assert_not_called()
    assert answered(bot) == [t("ru", "feedback_failed")]


async def test_album_parts_are_forwarded_without_sender_line():
    bot = bound_bot()
    feedback.waiting[42] = True

    await plain(bot, photo(7, album="a1"))
    await plain(bot, photo(8, album="a1"))
    await plain(bot, photo(9, album="a2"))

    assert forwarded(bot) == [7, 8]
    assert bot.send_message.await_count == 1
    assert answered(bot) == [t("ru", "feedback_thanks")]


@pytest.mark.parametrize("rejected", ["limit", "undelivered"])
async def test_album_parts_are_dropped_when_first_is_rejected(rejected):
    bot = bound_bot()
    limiter = RateLimiter(0 if rejected == "limit" else 5, 60)
    if rejected == "undelivered":
        # The first part fails, a later one would get through.
        bot.forward_message.side_effect = [
            TelegramForbiddenError(method=MagicMock(), message="no"),
            MagicMock(message_id=100),
        ]

    await command(bot, photo(7, album="a1", caption="/feedback x"), limiter=limiter)
    await plain(bot, photo(8, album="a1"))

    assert 8 not in forwarded(bot)


async def test_cancelled_album_part_does_not_break_the_others():
    bot = bound_bot()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_forward(*args):
        started.set()
        await release.wait()
        return MagicMock(message_id=100)

    bot.forward_message.side_effect = slow_forward
    first = asyncio.create_task(command(bot, photo(7, album="a1", caption="/feedback x")))
    await started.wait()
    cancelled = asyncio.create_task(plain(bot, photo(8, album="a1")))
    other = asyncio.create_task(plain(bot, photo(9, album="a1")))
    await asyncio.sleep(0)
    cancelled.cancel()
    release.set()
    await asyncio.gather(first, other)

    assert sorted(forwarded(bot)) == [7, 9]
    assert answered(bot) == [t("ru", "feedback_thanks")]


async def test_album_part_waits_for_the_captioned_first_one():
    bot = bound_bot()

    # The uncaptioned part reaches its handler first.
    await asyncio.gather(
        plain(bot, photo(8, album="a1")),
        command(bot, photo(7, album="a1", caption="/feedback x")),
    )

    assert sorted(forwarded(bot)) == [7, 8]


def test_not_command_filter_accepts_photos():
    assert not feedback.NOT_COMMAND.resolve(make_message("/today"))
    assert feedback.NOT_COMMAND.resolve(make_message("привет"))
    assert feedback.NOT_COMMAND.resolve(photo(1))


class FakeSession(BaseSession):
    """Records Bot API calls and yields to other tasks on each, like a real network call."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
        self.calls.append(method)
        await asyncio.sleep(0.01)
        return Message.model_validate(
            {"message_id": 100 + len(self.calls), "date": 0, "chat": {"id": 1, "type": "private"}}
        )

    async def close(self) -> None:
        pass

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError
        yield b""

    def forwarded(self) -> list[int]:
        return sorted(c.message_id for c in self.calls if isinstance(c, ForwardMessage))

    def replies(self) -> list[str]:
        """Feedback answers to the user, without other screens like /today."""
        texts = {t("ru", k) for k in ("feedback_prompt", "feedback_thanks", "feedback_failed")}
        return [c.text for c in self.calls if isinstance(c, SendMessage) and c.text in texts]


@pytest.fixture
def app():
    session = FakeSession()
    bot = Bot("42:TEST", session=session)
    # Bot.me() caches here; set it so Command filters don't call getMe.
    bot._me = User(id=42, is_bot=True, first_name="Bot", username="padel_bot")
    availability = MagicMock(venues=[])
    availability.get_availability = AsyncMock(return_value=Availability(day=date.today(), slots=[]))
    routers = [handlers.router, watch.router, feedback.router, handlers.group_router]
    dp = Dispatcher()
    dp.include_routers(*routers)
    deps = {
        "availability": availability,
        "stats": MagicMock(),
        "subscriptions": MagicMock(),
        "admin_ids": ADMINS,
        "slot_limiter": RateLimiter(10, 60),
        "refresh_limiter": RateLimiter(10, 60),
        "feedback_limiter": RateLimiter(10, 60),
    }

    async def feed(*messages: Message) -> None:
        # Concurrently, as start_polling does for one batch of updates.
        await asyncio.gather(
            *(
                dp.feed_update(bot, Update(update_id=m.message_id, message=m), **deps)
                for m in messages
            )
        )

    yield session, availability, feed
    # A router can belong to one dispatcher only; free them for the next test.
    for router in routers:
        router._parent_router = None


async def test_dispatcher_feedback_flow(app):
    session, availability, feed = app

    await feed(make_message("/feedback", message_id=1))
    # Another command while waiting is handled as usual and is not feedback.
    await feed(make_message("/today", message_id=2))
    availability.get_availability.assert_awaited_once()
    assert session.forwarded() == []

    await feed(make_message("нет кортов", message_id=3))
    await feed(make_message("ещё текст", message_id=4))

    assert session.forwarded() == [3]
    assert session.replies() == [t("ru", "feedback_prompt"), t("ru", "feedback_thanks")]


async def test_dispatcher_two_quick_messages_give_one_feedback(app):
    session, _, feed = app

    await feed(make_message("/feedback", message_id=1))
    await feed(make_message("раз", message_id=2), make_message("два", message_id=3))

    assert len(session.forwarded()) == 1
    assert session.replies().count(t("ru", "feedback_thanks")) == 1


async def test_dispatcher_album_is_forwarded_whole(app):
    session, _, feed = app

    await feed(make_message("/feedback", message_id=1))
    await feed(*(photo(i, album="a1") for i in (2, 3, 4)))

    assert session.forwarded() == [2, 3, 4]
    assert session.replies().count(t("ru", "feedback_thanks")) == 1


async def test_dispatcher_captioned_album(app):
    session, _, feed = app

    await feed(
        photo(2, album="a1", caption="/feedback вот"), photo(3, album="a1"), photo(4, album="a1")
    )

    assert session.forwarded() == [2, 3, 4]
