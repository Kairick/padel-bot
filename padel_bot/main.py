import asyncio
import logging
import sys
from collections.abc import Coroutine
from contextlib import suppress
from html import escape
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand

from padel_bot.bot.feedback import router as feedback_router
from padel_bot.bot.handlers import group_router, router
from padel_bot.bot.i18n import t
from padel_bot.bot.throttle import RateLimiter
from padel_bot.bot.watch import notification_message
from padel_bot.bot.watch import router as watch_router
from padel_bot.config import get_settings, load_venues
from padel_bot.db import connect
from padel_bot.domain import Lang
from padel_bot.monitoring.poller import Poller
from padel_bot.monitoring.store import SubscriptionStore
from padel_bot.reservio.client import ReservioClient
from padel_bot.reservio.service import AvailabilityService
from padel_bot.stats import Stats, StatsMiddleware

log = logging.getLogger(__name__)

COMMAND_KEYS = ["start", "today", "tomorrow", "watch", "subs", "feedback"]
# Handled but not in the menu: /days is an alias of /start, /stats is for admins.
HIDDEN_COMMANDS = ["days", "stats"]


class MonitorCrashed(RuntimeError):
    """The monitor died; the process exits so that Fly restarts it with a working one."""


def commands(lang: Lang) -> list[BotCommand]:
    return [BotCommand(command=c, description=t(lang, f"cmd_{c}")) for c in COMMAND_KEYS]


def build_dispatcher(stats: Stats) -> Dispatcher:
    dp = Dispatcher()
    dp.message.outer_middleware(StatsMiddleware(stats))
    dp.callback_query.outer_middleware(StatsMiddleware(stats))
    # The fallback router goes last: it takes everything the private ones rejected.
    dp.include_routers(router, watch_router, feedback_router, group_router)
    return dp


async def alert_admins(bot: Bot, admin_ids: frozenset[int], text: str) -> None:
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError as e:
            log.warning("alert not delivered to admin %s: %s", admin_id, e)


async def serve(
    polling: Coroutine[Any, Any, None],
    monitor: asyncio.Task[None] | None,
    bot: Bot,
    admin_ids: frozenset[int],
) -> None:
    """Run polling until it stops; if the monitor dies first, alert admins and crash.

    The poller survives failed cycles, so a dead monitor means a bug outside a cycle. The bot
    would go on answering while subscriptions stay silent; a restart is better than that.
    """
    if monitor is None:
        await polling
        return
    polling_task = asyncio.create_task(polling, name="polling")
    try:
        await asyncio.wait({polling_task, monitor}, return_when=asyncio.FIRST_COMPLETED)
        if polling_task.done():
            polling_task.result()
            return
        error = None if monitor.cancelled() else monitor.exception()
        log.error("monitor stopped, restarting the bot", exc_info=error)
        details = escape(repr(error), quote=False)
        await alert_admins(
            bot, admin_ids, f"⚠️ <b>Мониторинг упал</b>, бот перезапускается\n<code>{details}</code>"
        )
        raise MonitorCrashed from error
    finally:
        if not polling_task.done():
            polling_task.cancel()
            with suppress(asyncio.CancelledError):
                await polling_task


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    venues = load_venues(settings.venues_file)
    client = ReservioClient(settings.reservio_api_url)
    availability = AvailabilityService(client, venues, settings.cache_ttl_seconds)

    bot = Bot(
        settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    db = connect(settings.stats_db_path)
    salt = settings.stats_salt.get_secret_value() if settings.stats_salt else None
    stats = Stats(db, salt)
    subscriptions = SubscriptionStore(db)
    dp = build_dispatcher(stats)
    admin_ids = frozenset(settings.admin_ids)
    monitor: asyncio.Task[None] | None = None
    try:
        await bot.set_my_commands(commands("en"))
        await bot.set_my_commands(commands("ru"), language_code="ru")
        if settings.monitor_enabled:
            poller = Poller(
                bot,
                client,
                venues,
                subscriptions,
                settings.monitor_interval_seconds,
                render=notification_message,
            )
            monitor = asyncio.create_task(poller.run(), name="monitor")
        polling = dp.start_polling(
            bot,
            availability=availability,
            stats=stats,
            subscriptions=subscriptions,
            admin_ids=admin_ids,
            # Every slot tap creates Reservio draft orders, every refresh bypasses the cache.
            slot_limiter=RateLimiter(max_events=20, per_seconds=60),
            refresh_limiter=RateLimiter(max_events=5, per_seconds=60),
            feedback_limiter=RateLimiter(max_events=5, per_seconds=3600),
        )
        await serve(polling, monitor, bot, admin_ids)
    finally:
        if monitor is not None:
            monitor.cancel()
            # A crashed monitor is already logged; it must not skip closing the rest.
            with suppress(asyncio.CancelledError, Exception):
                await monitor
        await client.aclose()
        await bot.session.close()
        db.close()


def run() -> None:
    try:
        asyncio.run(main())
    except MonitorCrashed:
        sys.exit(1)  # already logged; a non-zero exit makes Fly restart the machine


if __name__ == "__main__":
    run()
