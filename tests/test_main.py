import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command

from padel_bot.bot import browse, feedback, start_links, watch
from padel_bot.main import (
    COMMAND_KEYS,
    HIDDEN_COMMANDS,
    MonitorCrashed,
    alert_admins,
    build_dispatcher,
    check_bot_settings,
    commands,
    serve,
)


def handled_commands(router: Router) -> set[str]:
    return {
        str(c)
        for handler in router.message.handlers
        for f in handler.filters or []
        if isinstance(f.callback, Command)
        for c in f.callback.commands
    }


def test_menu_commands_have_texts_in_both_languages():
    for lang in ("ru", "en"):
        menu = commands(lang)
        assert [c.command for c in menu] == COMMAND_KEYS
        assert all(c.description for c in menu)


def test_every_private_command_is_in_the_menu_or_deliberately_hidden():
    private = set().union(
        *(handled_commands(r) for r in (browse.browse_router, watch.watch_router))
    )
    private |= handled_commands(feedback.feedback_router)
    assert private == set(COMMAND_KEYS) | set(HIDDEN_COMMANDS)


def test_group_answers_every_user_command_but_not_stats():
    group = handled_commands(browse.group_browse_router)
    to_private = handled_commands(browse.fallback_router)
    assert group == {"start", "days", "today", "tomorrow"}
    assert group | to_private == set(COMMAND_KEYS) | {"days"}
    assert not group & to_private


def test_fallback_router_is_included_last():
    dp = build_dispatcher(MagicMock())
    assert dp.sub_routers == [
        start_links.start_links_router,
        browse.browse_router,
        browse.group_browse_router,
        watch.watch_router,
        feedback.feedback_router,
        browse.fallback_router,
    ]
    # A router can belong to one dispatcher only; free them for the next test.
    for r in dp.sub_routers:
        r._parent_router = None


async def test_monitor_crash_alerts_admins_and_stops_polling():
    polling_cancelled = asyncio.Event()

    async def polling() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            polling_cancelled.set()
            raise

    async def monitor() -> None:
        raise RuntimeError("bug")

    bot = MagicMock(send_message=AsyncMock())

    with pytest.raises(MonitorCrashed) as e:
        await serve(polling(), asyncio.create_task(monitor()), bot, frozenset({1}))

    assert isinstance(e.value.__cause__, RuntimeError)
    assert polling_cancelled.is_set()
    chat_id, text = bot.send_message.await_args.args
    assert chat_id == 1 and "RuntimeError('bug')" in text


async def test_polling_stop_ends_serving_without_alert():
    monitor = asyncio.create_task(asyncio.Event().wait())
    bot = MagicMock(send_message=AsyncMock())

    async def polling() -> None:
        return None

    await serve(polling(), monitor, bot, frozenset({1}))

    bot.send_message.assert_not_awaited()
    assert not monitor.done()  # main() cancels it on the way out
    monitor.cancel()


async def test_alert_reaches_admins_that_can_receive_it():
    bot = MagicMock()
    bot.send_message = AsyncMock(
        side_effect=[TelegramForbiddenError(method=MagicMock(), message="blocked"), None]
    )

    await alert_admins(bot, frozenset({1, 2}), "text")

    assert bot.send_message.await_count == 2


async def test_bot_settings_alert_when_groups_are_off():
    bot = MagicMock(send_message=AsyncMock())
    bot.me = AsyncMock(return_value=MagicMock(can_join_groups=False))

    await check_bot_settings(bot, frozenset({1}))

    chat_id, text = bot.send_message.await_args.args
    assert chat_id == 1 and "Allow Groups" in text


async def test_bot_settings_quiet_when_groups_are_on():
    bot = MagicMock(send_message=AsyncMock())
    bot.me = AsyncMock(return_value=MagicMock(can_join_groups=True))

    await check_bot_settings(bot, frozenset({1}))

    bot.send_message.assert_not_awaited()
