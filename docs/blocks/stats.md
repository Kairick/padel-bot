# Stats

**Purpose:** Anonymous usage statistics: unique users and group chats per day via a salted hash, aggregated action counters (group actions apart), and the admin summary text.
**Code:** `padel_bot/stats.py`

## Interface
- `Stats.track_user(user_id, lang)`, `Stats.track_group(chat_id)`, `Stats.track_event(event, venue=, hour=)` — never raise on SQLite errors (logged).
- `chat_event(event, chat_type)` — `group_<event>` outside private chats; used by [browse](browse.md).
- `Stats.summary() -> Summary` — users today/7d/30d/total, new in 7d, groups 7d/30d, events 7d, top venues/hours/langs 30d.
- `format_summary(summary, venue_names)` — Russian HTML text for `/stats` (the command handler lives in [browse](browse.md)).
- `StatsMiddleware` — aiogram outer middleware on messages and callbacks; tracks every non-bot user and the group chat it acts in.

## Owns
- Persistent: tables `daily_users` (day, user_hash, lang), `daily_groups` (day, chat_hash) and `events` (day, event, venue, hour, count) in the shared SQLite file.
- Contracts: event names `start`, `day_view`, `refresh`, `slot_view`, `watch_created`, `watch_deleted`, `feedback` (`EVENT_LABELS`); group ones `group_start`, `group_day_view`, `group_refresh`, `slot_link`, `watch_link` (`GROUP_EVENT_LABELS`).

## Depends on
- SQLite connection from `padel_bot/db.py` (shared with [subscriptions](subscriptions.md)).
- Shared `padel_bot/domain.py` — `detect_lang`, `TZ`.

## Config
- `STATS_SALT` — HMAC key, never stored; without it unique users are not counted (error logged, `/stats` warns). Must not change after launch.
- `STATS_DB_PATH` — SQLite file.

## Tests
- `tests/test_stats.py` — periods, aggregation, salt never stored, no-salt mode, empty summary, groups and group events, middleware; also hosts `db.py` and `Settings` tests.

## Notes
- A tap on a group URL button never reaches the bot: `slot_link` / `watch_link` are counted when the private chat opens the link, so taps of people who never press Start are lost (owner, 2026-11-04). `slot_link` comes on top of `slot_view`, which stays the total.
- Event names are free strings passed by callers; a typo silently creates a new counter *(inferred)*.
- Mixes storage, aiogram middleware and admin presentation in one module.
