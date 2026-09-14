import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from padel_bot.bot.handlers import router
from padel_bot.config import get_settings, load_venues
from padel_bot.reservio.client import ReservioClient
from padel_bot.reservio.service import AvailabilityService

COMMANDS = [
    BotCommand(command="start", description="Выбрать день"),
    BotCommand(command="today", description="Свободные корты сегодня"),
    BotCommand(command="tomorrow", description="Свободные корты завтра"),
]


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
    dp = Dispatcher()
    dp.include_router(router)
    try:
        await bot.set_my_commands(COMMANDS)
        await dp.start_polling(bot, availability=availability)
    finally:
        await client.aclose()
        await bot.session.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
