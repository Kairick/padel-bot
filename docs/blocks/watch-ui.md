# Watch UI

**Purpose:** Telegram screens for subscriptions to freed courts: Watch button, hour grid, subscription card with toggles, `/watch`, `/subs`.
**Code:** `padel_bot/bot/watch.py`

## Interface
- Commands: `/watch` (day picker with a hint), `/subs` (list of the chat's subscriptions), `/start wh_<day>_<rng>` (`cmd_start_watch`) — the Watch link of a group message, opens the hour grid (an outdated day falls back to `/watch`).
- Callbacks: `WATCH` (start), `WatchDayCb` (hour grid), `WatchHourCb` (create subscription, open card), `WatchCb` actions `open`, `del`, `done`, `kind`, `len`, `club`, `courts`.
- `notification_message(freed, venues, hidden, today, lang)` — text + keyboard of a freed-courts notification; `main.py` hands it to the [monitor](monitor.md).
- Pure helpers: `watch_hours`, `toggle_kind`, `toggle_length`, `toggle_club`, `toggle_courts`, `hours_view`, `card_view`, `subs_view`.

## Owns
- Persistent: nothing directly — all writes go through [subscriptions](subscriptions.md) (`create`, `update`, `delete`, `set_lang`).
- In-memory: nothing; stateless by design, every step's state is in callback data or the stored subscription.

## Depends on
- [subscriptions](subscriptions.md) — CRUD, limits (`MAX_SUBSCRIPTIONS`), errors, `Subscription` model and hour constants.
- [bot-views](bot-views.md) — callback data, `days_keyboard`, `day_title`, `render_notification`, `notification_keyboard`.
- [availability](availability.md) — venue list, day view.
- Shared `padel_bot/bot/common.py` — `private_router`, `resolve_day`, `build_day_view`, `safe_edit`, `answer_quietly`, `lang_of`; `padel_bot/domain.py`.
- [stats](stats.md) — `watch_created`, `watch_deleted`, `day_view` events.

## Config
- none

## Tests
- `tests/test_watch.py` — toggles, card/hour/subs views, callback-data size, create-once, limit screen, owner check, delete, done, `/subs`; notification rendering in `tests/test_poller.py`.

## Notes
- Card actions check `sub.chat_id == chat_id`: a forwarded or foreign card is "stale".
- A toggle that collides with an existing subscription shows `watch_duplicate`.
- Toggle logic (domain rules on hours and length) lives in the UI module *(inferred: candidate to move next to the model)*.
