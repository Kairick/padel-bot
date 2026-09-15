import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from padel_bot.bot.handlers import group_router, router
from padel_bot.bot.i18n import Lang, t
from padel_bot.bot.throttle import RateLimiter
from padel_bot.bot.watch import router as watch_router
from padel_bot.config import get_settings, load_venues
from padel_bot.db import connect
from padel_bot.monitoring.poller import Poller
from padel_bot.monitoring.store import SubscriptionStore
from padel_bot.reservio.client import ReservioClient
from padel_bot.reservio.service import AvailabilityService
from padel_bot.stats import Stats, StatsMiddleware

log = logging.getLogger(__name__)

COMMAND_KEYS = ["start", "today", "tomorrow", "watch", "subs"]


def log_monitor_exit(task: asyncio.Task[None]) -> None:
    # The poller loop survives failed cycles, so this means a bug outside a cycle.
    if not task.cancelled() and (error := task.exception()) is not None:
        log.error("monitor stopped, no more notifications until restart", exc_info=error)


def commands(lang: Lang) -> list[BotCommand]:
    return [BotCommand(command=c, description=t(lang, f"cmd_{c}")) for c in COMMAND_KEYS]


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
    dp = Dispatcher()
    dp.message.outer_middleware(StatsMiddleware(stats))
    dp.callback_query.outer_middleware(StatsMiddleware(stats))
    dp.include_routers(router, watch_router, group_router)
    monitor: asyncio.Task[None] | None = None
    try:
        await bot.set_my_commands(commands("en"))
        await bot.set_my_commands(commands("ru"), language_code="ru")
        if settings.monitor_enabled:
            poller = Poller(bot, client, venues, subscriptions, settings.monitor_interval_seconds)
            monitor = asyncio.create_task(poller.run(), name="monitor")
            monitor.add_done_callback(log_monitor_exit)
        await dp.start_polling(
            bot,
            availability=availability,
            stats=stats,
            subscriptions=subscriptions,
            admin_ids=frozenset(settings.admin_ids),
            # Every slot tap creates Reservio draft orders, every refresh bypasses the cache.
            slot_limiter=RateLimiter(max_events=20, per_seconds=60),
            refresh_limiter=RateLimiter(max_events=5, per_seconds=60),
        )
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
    asyncio.run(main())


if __name__ == "__main__":
    run()
