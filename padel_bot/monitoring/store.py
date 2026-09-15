"""Subscriptions, their known matches and per-service polling state in SQLite.

All timestamps are stored as ISO strings in the Batumi timezone, so they compare as text.
"""

import logging
import sqlite3
from collections.abc import Collection, Iterable
from dataclasses import replace
from datetime import date, datetime

from padel_bot.bot.i18n import Lang
from padel_bot.config import TZ
from padel_bot.monitoring.matcher import CyclePlan
from padel_bot.monitoring.models import KnownMatch, MatchKey, ServiceState, Subscription
from padel_bot.reservio.service import current_play_day

log = logging.getLogger(__name__)

MAX_SUBSCRIPTIONS = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    lang TEXT NOT NULL,
    venue_key TEXT,
    day TEXT,
    weekday INTEGER,
    hour_from INTEGER NOT NULL,
    hours INTEGER NOT NULL,
    min_courts INTEGER NOT NULL,
    changed_at TEXT NOT NULL,
    CHECK ((day IS NULL) <> (weekday IS NULL)),
    CHECK (weekday IS NULL OR weekday BETWEEN 0 AND 6),
    CHECK (hour_from BETWEEN 7 AND 25),
    CHECK (hours BETWEEN 1 AND 3),
    CHECK (hour_from + hours <= 26),
    CHECK (min_courts IN (1, 2))
);
CREATE UNIQUE INDEX IF NOT EXISTS subscriptions_unique ON subscriptions (
    chat_id, COALESCE(venue_key, ''), COALESCE(day, ''), COALESCE(weekday, -1),
    hour_from, hours, min_courts
);
CREATE TABLE IF NOT EXISTS subscription_matches (
    subscription_id INTEGER NOT NULL REFERENCES subscriptions (id) ON DELETE CASCADE,
    venue_key TEXT NOT NULL,
    slot_start TEXT NOT NULL,
    notified_at TEXT,
    gone_at TEXT,
    PRIMARY KEY (subscription_id, venue_key, slot_start)
);
CREATE TABLE IF NOT EXISTS poll_state (
    service_id TEXT PRIMARY KEY,
    venue_key TEXT NOT NULL,
    last_ok_at TEXT NOT NULL,
    horizon TEXT NOT NULL
);
"""

COLUMNS = "id, chat_id, lang, venue_key, day, weekday, hour_from, hours, min_courts, changed_at"


class SubscriptionLimitError(Exception):
    pass


class DuplicateSubscriptionError(Exception):
    def __init__(self, existing_id: int) -> None:
        super().__init__(f"same subscription already exists: {existing_id}")
        self.existing_id = existing_id


def ts(moment: datetime) -> str:
    return moment.astimezone(TZ).isoformat()


def parse_ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _subscription(row: tuple) -> Subscription:
    id_, chat_id, lang, venue_key, day, weekday, hour_from, hours, min_courts, changed_at = row
    return Subscription(
        id=id_,
        chat_id=chat_id,
        lang="ru" if lang == "ru" else "en",
        venue_key=venue_key,
        day=date.fromisoformat(day) if day else None,
        weekday=weekday,
        hour_from=hour_from,
        hours=hours,
        min_courts=min_courts,
        changed_at=datetime.fromisoformat(changed_at),
    )


class SubscriptionStore:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db
        self._db.executescript(SCHEMA)

    # Subscriptions

    def create(
        self,
        *,
        chat_id: int,
        lang: Lang,
        hour_from: int,
        day: date | None = None,
        weekday: int | None = None,
        venue_key: str | None = None,
        hours: int = 1,
        min_courts: int = 1,
        now: datetime | None = None,
    ) -> Subscription:
        draft = Subscription(
            id=0,
            chat_id=chat_id,
            lang=lang,
            venue_key=venue_key,
            day=day,
            weekday=weekday,
            hour_from=hour_from,
            hours=hours,
            min_courts=min_courts,
            changed_at=now or datetime.now(TZ),
        )
        with self._db:
            self._drop_expired(draft.changed_at)
            if (existing := self._find_same(draft)) is not None:
                raise DuplicateSubscriptionError(existing)
            if self.count_for_chat(chat_id) >= MAX_SUBSCRIPTIONS:
                raise SubscriptionLimitError
            cur = self._db.execute(
                "INSERT INTO subscriptions (chat_id, lang, venue_key, day, weekday, hour_from, "
                "hours, min_courts, changed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    chat_id,
                    lang,
                    venue_key,
                    day.isoformat() if day else None,
                    weekday,
                    hour_from,
                    hours,
                    min_courts,
                    ts(draft.changed_at),
                ),
            )
        return replace(draft, id=cur.lastrowid or 0)

    def update(self, sub: Subscription, now: datetime | None = None) -> Subscription:
        """Save changed conditions of `sub` (language is kept as stored, see `set_lang`)."""
        updated = replace(sub, changed_at=now or datetime.now(TZ))
        with self._db:
            if (existing := self._find_same(updated)) is not None:
                raise DuplicateSubscriptionError(existing)
            self._db.execute(
                "UPDATE subscriptions SET venue_key = ?, day = ?, weekday = ?, hour_from = ?, "
                "hours = ?, min_courts = ?, changed_at = ? WHERE id = ?",
                (
                    updated.venue_key,
                    updated.day.isoformat() if updated.day else None,
                    updated.weekday,
                    updated.hour_from,
                    updated.hours,
                    updated.min_courts,
                    ts(updated.changed_at),
                    updated.id,
                ),
            )
        return updated

    def get(self, sub_id: int) -> Subscription | None:
        row = self._db.execute(
            f"SELECT {COLUMNS} FROM subscriptions WHERE id = ?", (sub_id,)
        ).fetchone()
        return _subscription(row) if row else None

    def list_for_chat(self, chat_id: int, now: datetime) -> list[Subscription]:
        # Expired date subscriptions go first: the poller doesn't run at night or when disabled.
        with self._db:
            self._drop_expired(now)
        rows = self._db.execute(
            f"SELECT {COLUMNS} FROM subscriptions WHERE chat_id = ? ORDER BY id", (chat_id,)
        )
        return [_subscription(row) for row in rows]

    def count_for_chat(self, chat_id: int) -> int:
        sql = "SELECT COUNT(*) FROM subscriptions WHERE chat_id = ?"
        return int(self._db.execute(sql, (chat_id,)).fetchone()[0])

    def all(self) -> list[Subscription]:
        return [
            _subscription(row)
            for row in self._db.execute(f"SELECT {COLUMNS} FROM subscriptions ORDER BY id")
        ]

    def has_subscriptions(self) -> bool:
        return self._db.execute("SELECT 1 FROM subscriptions LIMIT 1").fetchone() is not None

    def set_lang(self, chat_id: int, lang: Lang) -> None:
        # Doesn't touch changed_at: a language switch must not re-baseline matches.
        with self._db:
            self._db.execute(
                "UPDATE subscriptions SET lang = ? WHERE chat_id = ? AND lang <> ?",
                (lang, chat_id, lang),
            )

    def delete(self, sub_id: int, chat_id: int) -> bool:
        with self._db:
            cur = self._db.execute(
                "DELETE FROM subscriptions WHERE id = ? AND chat_id = ?", (sub_id, chat_id)
            )
        return cur.rowcount > 0

    def delete_chat(self, chat_id: int) -> int:
        with self._db:
            cur = self._db.execute("DELETE FROM subscriptions WHERE chat_id = ?", (chat_id,))
        return cur.rowcount

    def is_unchanged(self, sub: Subscription) -> bool:
        """True if `sub` still exists and nobody changed it since it was read."""
        row = self._db.execute(
            "SELECT changed_at FROM subscriptions WHERE id = ?", (sub.id,)
        ).fetchone()
        return row is not None and row[0] == ts(sub.changed_at)

    # Polling

    def known_matches(self) -> dict[int, dict[MatchKey, KnownMatch]]:
        result: dict[int, dict[MatchKey, KnownMatch]] = {}
        rows = self._db.execute(
            "SELECT subscription_id, venue_key, slot_start, notified_at, gone_at "
            "FROM subscription_matches"
        )
        for sub_id, venue_key, start, notified_at, gone_at in rows:
            key = (venue_key, datetime.fromisoformat(start))
            result.setdefault(sub_id, {})[key] = KnownMatch(
                parse_ts(notified_at), parse_ts(gone_at)
            )
        return result

    def poll_state(self) -> dict[str, ServiceState]:
        rows = self._db.execute("SELECT service_id, venue_key, last_ok_at, horizon FROM poll_state")
        return {
            service_id: ServiceState(
                venue_key, datetime.fromisoformat(last_ok_at), datetime.fromisoformat(horizon)
            )
            for service_id, venue_key, last_ok_at, horizon in rows
        }

    def apply_cycle(self, plan: CyclePlan, now: datetime) -> None:
        """Write everything a cycle decided silently, in one transaction.

        A subscription changed while the cycle was running is skipped: its next cycle
        re-baselines it anyway.
        """
        with self._db:
            for sp in plan.subscriptions:
                if not self.is_unchanged(sp.subscription):
                    continue
                sub_id = sp.subscription.id
                self._db.executemany(
                    "DELETE FROM subscription_matches WHERE subscription_id = ? AND venue_key = ?",
                    [(sub_id, venue_key) for venue_key in sp.reset_venues],
                )
                self._db.executemany(
                    "INSERT INTO subscription_matches (subscription_id, venue_key, slot_start) "
                    "VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                    self._keys(sub_id, sp.insert),
                )
                self._db.executemany(
                    "UPDATE subscription_matches SET gone_at = ? "
                    "WHERE subscription_id = ? AND venue_key = ? AND slot_start = ?",
                    [(ts(now), *key) for key in self._keys(sub_id, sp.set_gone)],
                )
                self._db.executemany(
                    "UPDATE subscription_matches SET gone_at = NULL "
                    "WHERE subscription_id = ? AND venue_key = ? AND slot_start = ?",
                    self._keys(sub_id, sp.clear_gone),
                )
            self._db.executemany(
                "INSERT INTO poll_state (service_id, venue_key, last_ok_at, horizon) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (service_id) DO UPDATE SET "
                "venue_key = excluded.venue_key, last_ok_at = excluded.last_ok_at, "
                "horizon = excluded.horizon",
                [
                    (service_id, s.venue_key, ts(s.last_ok_at), ts(s.horizon))
                    for service_id, s in plan.service_states.items()
                ],
            )

    def mark_notified(
        self, sent: Iterable[tuple[Subscription, Collection[MatchKey]]], now: datetime
    ) -> None:
        with self._db:
            for sub, keys in sent:
                if not self.is_unchanged(sub):
                    continue
                self._db.executemany(
                    "INSERT INTO subscription_matches "
                    "(subscription_id, venue_key, slot_start, notified_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (subscription_id, venue_key, slot_start) DO UPDATE SET "
                    "notified_at = excluded.notified_at, gone_at = NULL",
                    [(*key, ts(now)) for key in self._keys(sub.id, keys)],
                )

    def cleanup(self, now: datetime, venue_keys: Collection[str], service_ids: Collection[str]):
        """Drop finished date subscriptions, removed clubs and services, past matches."""
        venue_marks = ", ".join("?" * len(venue_keys))
        service_marks = ", ".join("?" * len(service_ids))
        with self._db:
            self._drop_expired(now)
            orphans = self._db.execute(
                "SELECT id, venue_key FROM subscriptions "
                f"WHERE venue_key IS NOT NULL AND venue_key NOT IN ({venue_marks})",
                tuple(venue_keys),
            ).fetchall()
            for sub_id, venue_key in orphans:
                log.warning(
                    "monitor: deleting subscription %d for removed club %s", sub_id, venue_key
                )
                self._db.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))
            self._db.execute(
                f"DELETE FROM poll_state WHERE service_id NOT IN ({service_marks})",
                tuple(service_ids),
            )
            self._db.execute(
                "DELETE FROM subscription_matches WHERE slot_start <= ?",
                (ts(now.replace(microsecond=0)),),
            )

    def _drop_expired(self, now: datetime) -> None:
        """A date subscription lives until 06:00 after its play day. Call inside a transaction."""
        self._db.execute(
            "DELETE FROM subscriptions WHERE day IS NOT NULL AND day < ?",
            (current_play_day(now).isoformat(),),
        )

    def _find_same(self, sub: Subscription) -> int | None:
        row = self._db.execute(
            "SELECT id FROM subscriptions WHERE chat_id = ? AND id <> ? "
            "AND COALESCE(venue_key, '') = COALESCE(?, '') AND COALESCE(day, '') = COALESCE(?, '') "
            "AND COALESCE(weekday, -1) = COALESCE(?, -1) "
            "AND hour_from = ? AND hours = ? AND min_courts = ?",
            (
                sub.chat_id,
                sub.id,
                sub.venue_key,
                sub.day.isoformat() if sub.day else None,
                sub.weekday,
                sub.hour_from,
                sub.hours,
                sub.min_courts,
            ),
        ).fetchone()
        return row[0] if row else None

    @staticmethod
    def _keys(sub_id: int, keys: Iterable[MatchKey]) -> list[tuple[int, str, str]]:
        return [(sub_id, venue_key, ts(start)) for venue_key, start in keys]
