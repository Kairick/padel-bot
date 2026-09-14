import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from padel_bot.bot.handlers import router
from padel_bot.bot.i18n import Lang, t
from padel_bot.config import get_settings, load_venues
from padel_bot.reservio.client import ReservioClient
from padel_bot.reservio.service import AvailabilityService
from padel_bot.stats import Stats, StatsMiddleware

COMMAND_KEYS = ["start", "today", "tomorrow"]


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
    stats = Stats(settings.stats_db_path)
    dp = Dispatcher()
    dp.message.outer_middleware(StatsMiddleware(stats))
    dp.callback_query.outer_middleware(StatsMiddleware(stats))
    dp.include_router(router)
    try:
        await bot.set_my_commands(commands("en"))
        await bot.set_my_commands(commands("ru"), language_code="ru")
        await dp.start_polling(
            bot,
            availability=availability,
            stats=stats,
            admin_ids=frozenset(settings.admin_ids),
        )
    finally:
        await client.aclose()
        await bot.session.close()
        stats.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
