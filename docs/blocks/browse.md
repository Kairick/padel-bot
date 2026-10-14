# Browse

**Purpose:** The main Telegram flow — pick a day, see free slots, tap a time to get booking links — plus the group fallback router.
**Code:** `padel_bot/bot/browse.py`

## Interface
- Commands (private chats): `/start` and `/days` (same handler: day picker), `/today`, `/tomorrow`, `/stats` (admin-only, see [stats](stats.md)).
- Callbacks: `DAYS` (day picker), `DayCb` (day view, range switch, refresh), `SlotCb` (slot view with booking links), `NOOP`.
- `browse_router` — private chats and the bot's own messages only; `group_router` — answers group commands (except `/stats`) with "write me in private" and catches every rejected callback.

## Owns
- External effects: each slot tap creates Reservio draft orders (through [availability](availability.md) `booking_links`).
- In-memory: nothing of its own; `slot_limiter` (20/min) and `refresh_limiter` (5/min) are injected by `main.py`.

## Depends on
- [availability](availability.md) — slots, booking links, venue list.
- [bot-views](bot-views.md) — texts, keyboards, callback data, `parse_day`.
- [stats](stats.md) — `track_event`, `summary`, `format_summary`.
- Shared `padel_bot/bot/common.py` (handler helpers), `padel_bot/domain.py`, `padel_bot/bot/throttle.py`, `padel_bot/bot/i18n.py`.

## Config
- `ADMIN_IDS` — who may run `/stats`; when empty, `/stats` replies with the caller's id.

## Tests
- `tests/test_browse.py` (answer-before-Reservio, stale/garbage/out-of-window days, rate limits), `tests/test_routing.py` (private vs fallback router, failed venue notice).

## Notes
- Private-only routing is a security rule: a draft-order link works for anyone who sees it (`common.py:27`).
- `/days` is a hidden alias of `/start` and `/stats` is admin-only: both are off the menu on purpose (`HIDDEN_COMMANDS`, `main.py:34`); `tests/test_main.py` checks every handled command is in the menu or hidden.
- `/stats` in a group is ignored silently: the group shouldn't learn the admin command exists.
