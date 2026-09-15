from datetime import datetime

import pytest
from pydantic import ValidationError

from padel_bot.config import TZ, Settings
from padel_bot.db import connect
from padel_bot.stats import Stats, format_summary

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=TZ)
SALT = "test-salt"


def at(day: int) -> datetime:
    return datetime(2026, 9, day, 12, 0, tzinfo=TZ)


def test_unique_users_by_period(tmp_path):
    stats = Stats(connect(tmp_path / "stats.sqlite3"), SALT)
    stats.track_user(1, "ru", now=at(20))
    stats.track_user(1, "ru", now=at(20))  # same user, same day
    stats.track_user(2, "en", now=at(20))
    stats.track_user(1, "ru", now=at(18))
    stats.track_user(3, "ru", now=at(10))  # 10 days ago: in 30d, not in 7d
    stats.track_user(4, "en", now=datetime(2026, 7, 1, 12, 0, tzinfo=TZ))

    s = stats.summary(now=NOW)

    assert s.users_counted
    assert (s.users_today, s.users_7d, s.users_30d, s.users_total) == (2, 2, 3, 4)
    assert s.new_7d == 2
    assert s.langs_30d == {"ru": 2, "en": 1}


def test_events_are_aggregated(tmp_path):
    stats = Stats(connect(tmp_path / "stats.sqlite3"), SALT)
    stats.track_event("start", now=at(20))
    stats.track_event("day_view", now=at(19))
    stats.track_event("day_view", now=at(20))
    for _ in range(3):
        stats.track_event("slot_view", venue="pp", hour=19, now=at(20))
    stats.track_event("slot_view", venue="gp", hour=18, now=at(20))
    stats.track_event("watch_created", now=at(20))

    s = stats.summary(now=NOW)

    assert s.events_7d == {"start": 1, "day_view": 2, "slot_view": 4, "watch_created": 1}
    assert s.top_venues_30d == [("pp", 3), ("gp", 1)]
    assert s.top_hours_30d == [(19, 3), (18, 1)]
    text = format_summary(s, {"pp": "Padel Port", "gp": "Grand Padel"})
    assert "открыли время: 4" in text
    assert "создали подписку: 1" in text
    assert "удалили подписку: 0" in text
    assert "клубы: Padel Port 3 · Grand Padel 1" in text
    assert "популярные часы: 19:00 3 · 18:00 1" in text
    assert "STATS_SALT" not in text


def test_salt_is_never_stored_and_hashes_are_stable(tmp_path):
    path = tmp_path / "stats.sqlite3"
    db = connect(path)
    stats = Stats(db, SALT)
    stats.track_user(987654321, "ru", now=NOW)
    first_hash = stats.user_hash(987654321)
    db.close()

    db = connect(path)
    reopened = Stats(db, SALT)
    assert reopened.user_hash(987654321) == first_hash
    assert reopened.summary(now=NOW).users_total == 1  # same person after restart
    dump = "\n".join(db.iterdump())
    assert "987654321" not in dump
    assert SALT not in dump
    assert first_hash in dump
    db.close()

    other = Stats(connect(tmp_path / "other.sqlite3"), "other-salt")
    assert other.user_hash(987654321) != first_hash


def test_without_salt_users_are_not_counted_but_events_are(tmp_path):
    path = tmp_path / "stats.sqlite3"
    for _ in range(2):  # restarts must not inflate anything
        db = connect(path)
        stats = Stats(db)
        stats.track_user(1, "ru", now=NOW)
        stats.track_event("start", now=NOW)
        db.close()

    stats = Stats(connect(path))
    s = stats.summary(now=NOW)
    assert not s.users_counted
    assert (s.users_today, s.users_total) == (0, 0)
    assert s.events_7d == {"start": 2}
    assert "не задан STATS_SALT" in format_summary(s, {})


def test_empty_summary_formats(tmp_path):
    stats = Stats(connect(tmp_path / "stats.sqlite3"), SALT)
    text = format_summary(stats.summary(now=NOW), {})
    assert "сегодня 0 · 7 дней 0 · 30 дней 0 · всего 0" in text
    assert "клубы: —" in text


def test_connection_uses_wal_and_foreign_keys(tmp_path):
    db = connect(tmp_path / "nested" / "bot.sqlite3")
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    db.close()


def test_monitor_interval_has_a_floor(monkeypatch):
    monkeypatch.setenv("MONITOR_INTERVAL_SECONDS", "6")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, bot_token="x")  # type: ignore[call-arg]


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "123, 456")
    monkeypatch.setenv("STATS_SALT", "from-env")
    settings = Settings(_env_file=None, bot_token="x")  # type: ignore[call-arg]
    assert settings.admin_ids == [123, 456]
    assert settings.stats_salt is not None
    assert settings.stats_salt.get_secret_value() == "from-env"
    assert settings.monitor_enabled
    assert settings.monitor_interval_seconds == 600

    monkeypatch.setenv("ADMIN_IDS", "")
    monkeypatch.delenv("STATS_SALT")
    monkeypatch.setenv("MONITOR_ENABLED", "false")
    settings = Settings(_env_file=None, bot_token="x")  # type: ignore[call-arg]
    assert settings.admin_ids == []
    assert settings.stats_salt is None
    assert not settings.monitor_enabled
