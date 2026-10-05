"""Basics shared by every part of the bot: timezone, play day, language. No project imports."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tbilisi")

# Clubs are open past midnight; a "play day" D covers [D 06:00, D+1 06:00).
DAY_START = time(6, 0)

type Lang = Literal["ru", "en"]

DEFAULT_LANG: Lang = "en"
# Telegram language codes whose users most likely read Russian.
RUSSIAN_CODES = {"ru", "uk", "be", "kk"}


@dataclass(frozen=True, slots=True)
class TimeRange:
    """Hours of a play day, e.g. 17..30 means 17:00 to 06:00 next day."""

    start_hour: int
    end_hour: int

    def contains(self, day: date, moment: datetime) -> bool:
        base = datetime.combine(day, time(0), TZ)
        start = base + timedelta(hours=self.start_hour)
        end = base + timedelta(hours=self.end_hour)
        return start <= moment < end


WHOLE_DAY = TimeRange(DAY_START.hour, DAY_START.hour + 24)


def current_play_day(now: datetime | None = None) -> date:
    """Play day that is going on right now (before 06:00 it's still the previous day)."""
    now = (now or datetime.now(TZ)).astimezone(TZ)
    return (now - timedelta(hours=DAY_START.hour)).date()


def detect_lang(language_code: str | None) -> Lang:
    if not language_code:
        return DEFAULT_LANG
    return "ru" if language_code.split("-")[0].lower() in RUSSIAN_CODES else "en"
