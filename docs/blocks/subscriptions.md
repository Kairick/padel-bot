# Subscriptions

**Purpose:** The subscription model and its SQLite storage: subscriptions, known matches per subscription, per-service polling state.
**Code:** `padel_bot/monitoring/models.py`, `padel_bot/monitoring/store.py`

## Interface
- Model: `Subscription` (`applies_to`, `matches`, `watches_venue`, `time_range`), `KnownMatch`, `ServiceState`, `MatchKey`.
- Cycle types shared with the monitor: `SubscriptionPlan`, `CyclePlan`, `FreedTime` (a time in a notification).
- Constants `FIRST_HOUR`, `LAST_HOUR`, `LAST_END_HOUR`, `MAX_HOURS`, `LEAD_TIME`; `slot_start`, `nearest_day`.
- `SubscriptionStore` CRUD: `create` (limit 5, unique), `update`, `get`, `list_for_chat`, `delete`, `delete_chat`, `set_lang`, `count_for_chat`.
- Polling side: `all`, `has_subscriptions`, `known_matches`, `poll_state`, `apply_cycle(plan, now)`, `mark_notified`, `is_unchanged`, `cleanup`.
- Errors: `SubscriptionLimitError`, `DuplicateSubscriptionError(existing_id)`.

## Owns
- Persistent: tables `subscriptions`, `subscription_matches` (FK cascade), `poll_state` in the shared SQLite file; schema created on construction (`store.py:22`), no migrations.
- Contracts: timestamps stored as ISO strings in Asia/Tbilisi so they compare as text.

## Depends on
- SQLite connection from `padel_bot/db.py` (shared with [stats](stats.md)).
- Shared `padel_bot/domain.py` — `TZ`, `Lang`, `TimeRange`, `current_play_day`.
- Shared `padel_bot/reservio/models.py` — `CourtSlot`, `Venue` (in the cycle types).

## Config
- `STATS_DB_PATH` — SQLite file (default `data/stats.sqlite3`; `/data/stats.sqlite3` on Fly).

## Tests
- `tests/test_store.py` — create/list, duplicates and limit, expiry of date subscriptions, schema CHECKs, `set_lang`, cascade, `apply_cycle` skip-if-changed, `mark_notified`, `cleanup`.

## Notes
- Stores Telegram `chat_id` in clear text (needed to notify) — the DB file is sensitive (README "Данные").
- A date subscription expires at 06:00 after its play day; expiry runs on create, list and every poll cycle.
- `changed_at` is the re-baseline trigger: any change makes the next cycle remember matches silently; `set_lang` deliberately does not touch it.
- Writes from two blocks share one connection; safe because nobody awaits inside `with db:` (`db.py:3`).
