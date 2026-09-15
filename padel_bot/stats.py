"""Anonymous usage statistics in SQLite.

Stores only a keyed hash of the Telegram user id per day (to count unique users) and
aggregated action counters that are not linked to users. The hash key (STATS_SALT) comes
from the environment and is never written to the database, so a leaked database file alone
is not enough to brute-force Telegram ids back from the hashes. Without STATS_SALT unique
users are not counted at all; action counters still work.
"""

import hashlib
import hmac
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from padel_bot.bot.i18n import detect_lang
from padel_bot.config import TZ

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_users (
    day TEXT NOT NULL,
    user_hash TEXT NOT NULL,
    lang TEXT NOT NULL,
    PRIMARY KEY (day, user_hash)
);
CREATE TABLE IF NOT EXISTS events (
    day TEXT NOT NULL,
    event TEXT NOT NULL,
    venue TEXT NOT NULL DEFAULT '',
    hour INTEGER NOT NULL DEFAULT -1,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, event, venue, hour)
);
"""

EVENT_LABELS = {
    "start": "открыли бота",
    "day_view": "смотрели день",
    "refresh": "обновляли",
    "slot_view": "открыли время",
    "watch_created": "создали подписку",
    "watch_deleted": "удалили подписку",
}


@dataclass(frozen=True, slots=True)
class Summary:
    users_today: int
    users_7d: int
    users_30d: int
    users_total: int
    new_7d: int
    events_7d: dict[str, int]
    top_venues_30d: list[tuple[str, int]]
    top_hours_30d: list[tuple[int, int]]
    langs_30d: dict[str, int]
    users_counted: bool


def local_date(now: datetime | None = None) -> date:
    return (now or datetime.now(TZ)).astimezone(TZ).date()


class Stats:
    def __init__(self, db: sqlite3.Connection, salt: str | None = None) -> None:
        self._db = db
        self._db.executescript(SCHEMA)
        self._salt = salt.encode() if salt else None
        if self._salt is None:
            log.error("STATS_SALT is not set: unique users are not counted until it is set")

    @property
    def counts_users(self) -> bool:
        return self._salt is not None

    def user_hash(self, user_id: int) -> str:
        if self._salt is None:
            raise RuntimeError("STATS_SALT is not set")
        return hmac.new(self._salt, str(user_id).encode(), hashlib.sha256).hexdigest()[:16]

    def track_user(self, user_id: int, lang: str, now: datetime | None = None) -> None:
        if self._salt is None:
            return
        try:
            with self._db:
                self._db.execute(
                    "INSERT OR IGNORE INTO daily_users (day, user_hash, lang) VALUES (?, ?, ?)",
                    (local_date(now).isoformat(), self.user_hash(user_id), lang),
                )
        except sqlite3.Error:
            log.exception("stats: failed to track user")

    def track_event(
        self, event: str, *, venue: str = "", hour: int = -1, now: datetime | None = None
    ) -> None:
        try:
            with self._db:
                self._db.execute(
                    "INSERT INTO events (day, event, venue, hour, count) VALUES (?, ?, ?, ?, 1) "
                    "ON CONFLICT (day, event, venue, hour) DO UPDATE SET count = count + 1",
                    (local_date(now).isoformat(), event, venue, hour),
                )
        except sqlite3.Error:
            log.exception("stats: failed to track event")

    def summary(self, now: datetime | None = None) -> Summary:
        today = local_date(now)
        d7 = (today - timedelta(days=6)).isoformat()
        d30 = (today - timedelta(days=29)).isoformat()

        def scalar(sql: str, *args: object) -> int:
            return int(self._db.execute(sql, args).fetchone()[0] or 0)

        def users_since(day: str) -> int:
            return scalar("SELECT COUNT(DISTINCT user_hash) FROM daily_users WHERE day >= ?", day)

        return Summary(
            users_counted=self.counts_users,
            users_today=users_since(today.isoformat()),
            users_7d=users_since(d7),
            users_30d=users_since(d30),
            users_total=scalar("SELECT COUNT(DISTINCT user_hash) FROM daily_users"),
            new_7d=scalar(
                "SELECT COUNT(*) FROM (SELECT user_hash FROM daily_users "
                "GROUP BY user_hash HAVING MIN(day) >= ?)",
                d7,
            ),
            events_7d={
                event: int(total)
                for event, total in self._db.execute(
                    "SELECT event, SUM(count) FROM events WHERE day >= ? GROUP BY event", (d7,)
                )
            },
            top_venues_30d=[
                (venue, int(total))
                for venue, total in self._db.execute(
                    "SELECT venue, SUM(count) AS total FROM events "
                    "WHERE day >= ? AND event = 'slot_view' "
                    "GROUP BY venue ORDER BY total DESC LIMIT 5",
                    (d30,),
                )
            ],
            top_hours_30d=[
                (int(hour), int(total))
                for hour, total in self._db.execute(
                    "SELECT hour, SUM(count) AS total FROM events "
                    "WHERE day >= ? AND event = 'slot_view' "
                    "GROUP BY hour ORDER BY total DESC, hour LIMIT 5",
                    (d30,),
                )
            ],
            langs_30d={
                lang: int(users)
                for lang, users in self._db.execute(
                    "SELECT lang, COUNT(DISTINCT user_hash) FROM daily_users "
                    "WHERE day >= ? GROUP BY lang ORDER BY 2 DESC",
                    (d30,),
                )
            },
        )


def format_summary(summary: Summary, venue_names: dict[str, str]) -> str:
    lines = [
        "📊 <b>Статистика</b>",
        "",
        "<b>Пользователи</b>",
        f"сегодня {summary.users_today} · 7 дней {summary.users_7d} · "
        f"30 дней {summary.users_30d} · всего {summary.users_total}",
        f"новые за 7 дней: {summary.new_7d}",
        "",
        "<b>Действия за 7 дней</b>",
    ]
    if not summary.users_counted:
        lines.insert(3, "⚠️ не задан STATS_SALT, уникальные пользователи не считаются")
    for event, label in EVENT_LABELS.items():
        lines.append(f"{label}: {summary.events_7d.get(event, 0)}")

    lines += ["", "<b>За 30 дней</b>"]
    venues = " · ".join(
        f"{escape(venue_names.get(key, key))} {total}" for key, total in summary.top_venues_30d
    )
    hours = " · ".join(f"{hour:02d}:00 {total}" for hour, total in summary.top_hours_30d)
    langs = " · ".join(f"{lang} {users}" for lang, users in summary.langs_30d.items())
    lines.append(f"клубы: {venues or '—'}")
    lines.append(f"популярные часы: {hours or '—'}")
    lines.append(f"языки: {langs or '—'}")
    return "\n".join(lines)


class StatsMiddleware(BaseMiddleware):
    """Counts every user that sends a message or presses a button."""

    def __init__(self, stats: Stats) -> None:
        self.stats = stats

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is not None and not user.is_bot:
            self.stats.track_user(user.id, detect_lang(user.language_code))
        return await handler(event, data)
