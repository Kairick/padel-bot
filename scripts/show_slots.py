"""Print availability from the live Reservio API without Telegram.

Usage: uv run python scripts/show_slots.py [today|tomorrow|YYYY-MM-DD] [m|a|e|w]
"""

import asyncio
import re
import sys
from datetime import date, timedelta

from padel_bot.bot.formatting import render_day
from padel_bot.bot.keyboards import RANGES
from padel_bot.config import ROOT, load_venues
from padel_bot.reservio.client import ReservioClient
from padel_bot.reservio.service import AvailabilityService, current_play_day


async def main(day_arg: str, rng: str) -> None:
    today = current_play_day()
    shortcuts = {"today": today, "tomorrow": today + timedelta(days=1)}
    day = shortcuts.get(day_arg) or date.fromisoformat(day_arg)
    client = ReservioClient()
    service = AvailabilityService(client, load_venues(ROOT / "venues.yaml"))
    label, time_range = RANGES[rng]
    try:
        result = await service.get_availability(day, time_range)
    finally:
        await client.aclose()
    print(re.sub(r"<[^>]+>", "", render_day(result, service.venues, label)))
    example = result.slots[0].booking_url if result.slots else "-"
    print(f"\n{len(result.slots)} slots; example link: {example}")


if __name__ == "__main__":
    args = sys.argv[1:]
    asyncio.run(main(args[0] if args else "tomorrow", args[1] if len(args) > 1 else "w"))
