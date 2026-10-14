# Stats

**Purpose:** Anonymous usage statistics: unique users per day via a salted hash, aggregated action counters, and the admin summary text.
**Code:** `padel_bot/stats.py`

## Interface
- `Stats.track_user(user_id, lang)`, `Stats.track_event(event, venue=, hour=)` — never raise on SQLite errors (logged).
- `Stats.summary() -> Summary` — users today/7d/30d/total, new in 7d, events 7d, top venues/hours/langs 30d.
- `format_summary(summary, venue_names)` — Russian HTML text for `/stats` (the command handler lives in [browse](browse.md)).
- `StatsMiddleware` — aiogram outer middleware on messages and callbacks; tracks every non-bot user.

## Owns
- Persistent: tables `daily_users` (day, user_hash, lang) and `events` (day, event, venue, hour, count) in the shared SQLite file.
- Contracts: event names `start`, `day_view`, `refresh`, `slot_view`, `watch_created`, `watch_deleted`, `feedback` (`EVENT_LABELS`).

## Depends on
- SQLite connection from `padel_bot/db.py` (shared with [subscriptions](subscriptions.md)).
- Shared `padel_bot/domain.py` — `detect_lang`, `TZ`.

## Config
- `STATS_SALT` — HMAC key, never stored; without it unique users are not counted (error logged, `/stats` warns). Must not change after launch.
- `STATS_DB_PATH` — SQLite file.

## Tests
- `tests/test_stats.py` — periods, aggregation, salt never stored, no-salt mode, empty summary; also hosts `db.py` and `Settings` tests.

## Notes
- Event names are free strings passed by callers; a typo silently creates a new counter *(inferred)*.
- Mixes storage, aiogram middleware and admin presentation in one module.
