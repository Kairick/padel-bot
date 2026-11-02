# Browse

**Purpose:** The main Telegram flow — pick a day, see free slots, tap a time to get booking links — in private chats; free slots only in groups, plus the fallback router.
**Code:** `padel_bot/bot/browse.py`

## Interface
- Commands (private chats): `/start` and `/days` (same handler: day picker), `/today`, `/tomorrow`, `/stats` (admin-only, see [stats](stats.md)); `/start s_<day>_<rng>_<v>_<hm>` (`cmd_start_slot`) — a slot link from a group message, opens the slot view.
- Commands (groups): `/start`, `/days`, `/today`, `/tomorrow` — the same day picker and day view.
- Callbacks: `DAYS` (day picker), `DayCb` (day view, range switch, refresh), `SlotCb` (slot view with booking links), `NOOP`.
- `browse_router` — private chats and the bot's own messages only; `group_browse_router` — groups, the bot's own messages only, `DAYS`/`DayCb`/`NOOP` callbacks (slot and Watch buttons there are `start_link` URLs to the private chat); `fallback_router` — answers `/watch`, `/subs`, `/feedback` in groups with "write me in private" and catches every rejected callback.

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
- `tests/test_browse.py` (answer-before-Reservio, stale/garbage/out-of-window days, rate limits), `tests/test_routing.py` (private, group and fallback routers, failed venue notice). Deep links: `tests/test_browse.py` (round trip, bad links, rate limit, which handler a `/start` reaches).

## Notes
- Booking is private-only, a security rule: a draft-order link works for anyone who sees it (`common.py:27`). Groups only browse; `slot_view` is never called for a group message.
- In a group the day message is shared: whoever switches the day or range changes it for everyone, in the tapper's language.
- `/days` is a hidden alias of `/start` and `/stats` is admin-only: both are off the menu on purpose (`HIDDEN_COMMANDS`, `main.py:34`); `tests/test_main.py` checks every handled command is in the menu or hidden.
- `/stats` in a group is ignored silently: the group shouldn't learn the admin command exists.
