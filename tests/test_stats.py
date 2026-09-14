from datetime import datetime

from padel_bot.config import TZ, Settings
from padel_bot.stats import Stats, format_summary

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=TZ)


def at(day: int) -> datetime:
    return datetime(2026, 9, day, 12, 0, tzinfo=TZ)


def test_unique_users_by_period(tmp_path):
    stats = Stats(tmp_path / "stats.sqlite3")
    stats.track_user(1, "ru", now=at(20))
    stats.track_user(1, "ru", now=at(20))  # same user, same day
    stats.track_user(2, "en", now=at(20))
    stats.track_user(1, "ru", now=at(18))
    stats.track_user(3, "ru", now=at(10))  # 11 days ago: in 30d, not in 7d
    stats.track_user(4, "en", now=datetime(2026, 7, 1, 12, 0, tzinfo=TZ))

    s = stats.summary(now=NOW)

    assert (s.users_today, s.users_7d, s.users_30d, s.users_total) == (2, 2, 3, 4)
    assert s.new_7d == 2
    assert s.langs_30d == {"ru": 2, "en": 1}
    stats.close()


def test_events_are_aggregated(tmp_path):
    stats = Stats(tmp_path / "stats.sqlite3")
    stats.track_event("start", now=at(20))
    stats.track_event("day_view", now=at(19))
    stats.track_event("day_view", now=at(20))
    for _ in range(3):
        stats.track_event("slot_view", venue="pp", hour=19, now=at(20))
    stats.track_event("slot_view", venue="gp", hour=18, now=at(20))

    s = stats.summary(now=NOW)

    assert s.events_7d == {"start": 1, "day_view": 2, "slot_view": 4}
    assert s.top_venues_30d == [("pp", 3), ("gp", 1)]
    assert s.top_hours_30d == [(19, 3), (18, 1)]
    text = format_summary(s, {"pp": "Padel Port", "gp": "Grand Padel"})
    assert "открыли время: 4" in text
    assert "клубы: Padel Port 3 · Grand Padel 1" in text
    assert "популярные часы: 19:00 3 · 18:00 1" in text
    stats.close()


def test_raw_ids_are_not_stored_and_salt_persists(tmp_path):
    path = tmp_path / "stats.sqlite3"
    stats = Stats(path)
    stats.track_user(987654321, "ru", now=NOW)
    first_hash = stats.user_hash(987654321)
    stats.close()

    reopened = Stats(path)
    assert reopened.user_hash(987654321) == first_hash
    dump = "\n".join(reopened._db.iterdump())
    assert "987654321" not in dump
    assert first_hash in dump
    reopened.close()

    other = Stats(tmp_path / "other.sqlite3")
    assert other.user_hash(987654321) != first_hash
    other.close()


def test_empty_summary_formats(tmp_path):
    stats = Stats(tmp_path / "stats.sqlite3")
    text = format_summary(stats.summary(now=NOW), {})
    assert "сегодня 0 · 7 дней 0 · 30 дней 0 · всего 0" in text
    assert "клубы: —" in text
    stats.close()


def test_admin_ids_from_env(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "123, 456")
    settings = Settings(_env_file=None, bot_token="x")  # type: ignore[call-arg]
    assert settings.admin_ids == [123, 456]

    monkeypatch.setenv("ADMIN_IDS", "")
    assert Settings(_env_file=None, bot_token="x").admin_ids == []  # type: ignore[call-arg]
