# Browse

**Purpose:** The main Telegram flow — pick a day, see free slots, tap a time to get booking links — plus private-chat routing and the handler helpers other bot blocks reuse.
**Code:** `padel_bot/bot/handlers.py`

## Interface
- Commands (private chats): `/start` and `/days` (same handler: day picker), `/today`, `/tomorrow`, `/stats` (admin-only, see [stats](stats.md)).
- Callbacks: `DAYS` (day picker), `DayCb` (day view, range switch, refresh), `SlotCb` (slot view with booking links), `NOOP`.
- `router` — private chats and the bot's own messages only; `group_router` — answers group commands with "write me in private" and catches every rejected callback.
- Helpers imported by [watch-ui](watch-ui.md) and [feedback](feedback.md): `private_router`, `lang_of`, `answer_quietly`, `safe_edit`, `resolve_day`, `build_day_view`.

## Owns
- External effects: each slot tap creates Reservio draft orders (through [availability](availability.md) `booking_links`).
- In-memory: nothing of its own; `slot_limiter` (20/min) and `refresh_limiter` (5/min) are injected by `main.py`.

## Depends on
- [availability](availability.md) — slots, booking links, venue list, `current_play_day`.
- [bot-views](bot-views.md) — texts, keyboards, callback data, `parse_day`.
- [stats](stats.md) — `track_event`, `summary`, `format_summary`.
- Shared `padel_bot/bot/throttle.py`, `padel_bot/bot/i18n.py`.

## Config
- `ADMIN_IDS` — who may run `/stats`; when empty, `/stats` replies with the caller's id.

## Tests
- `tests/test_handlers.py` (answer-before-Reservio, stale/garbage/out-of-window days, rate limits), `tests/test_routing.py` (private vs fallback router, failed venue notice).

## Notes
- Private-only routing is a security rule: a draft-order link works for anyone who sees it (`handlers.py:34`).
- `/days` is registered (`handlers.py:110`) but missing from the command menu `COMMAND_KEYS` (`main.py:25`) and has no `cmd_days` text — a gap; `/days` is meant for everyone (owner, 2026-10-05).
- `/stats` absent from the menu is intentional: admin-only by design (owner, 2026-10-05).
- The module is both a block and a mini toolkit for other handlers (shared helpers live inside one block).
