# Browse

**Purpose:** The main Telegram flow — pick a day, see free slots, tap a time to get booking links — in private chats; a browse-only day view in groups; the fallback router.
**Code:** `padel_bot/bot/browse.py`

## Interface
- Private commands: `/start` and `/days` (day picker), `/today`, `/tomorrow`, `/stats` (admin-only, see [stats](stats.md)). Slot links from group messages are opened by [start-links](start-links.md) with `slot_view`.
- Group commands: `/start`, `/days`, `/today`, `/tomorrow` — the same day picker and day view.
- Callbacks: `DAYS` (day picker), `DayCb` (day view, range switch, refresh), `SlotCb` (slot view with booking links, private only), `NOOP`.
- Routers: `browse_router` (private chats, bot's own messages); `group_browse_router` (groups, bot's own messages: `DAYS`, `DayCb`, `NOOP`); `fallback_router` (included last: `/watch`, `/subs`, `/feedback` in groups → "write me in private", plus every callback the others rejected).
- `slot_view` — booking links of a slot, or the day view with a "taken" / "club failed" notice; shared by the `SlotCb` tap and [start-links](start-links.md). `cmd_start` is also start-links' fallback screen.

## Owns
- External effects: each slot view creates Reservio draft orders (through [availability](availability.md) `booking_links`).
- In-memory: nothing of its own; `slot_limiter` (20/min, also for slot links) and `refresh_limiter` (5/min) are injected by `main.py`.

## Depends on
- [availability](availability.md) — slots, booking links, venue list.
- [bot-views](bot-views.md) — texts, keyboards (group mode via `bot_username`), callback data, deep links, `parse_day`.
- [stats](stats.md) — `track_event`, `summary`, `format_summary`.
- Shared `padel_bot/bot/common.py` (routers, `link_target`, handler helpers), `padel_bot/domain.py`, `padel_bot/bot/throttle.py`, `padel_bot/bot/i18n.py`.

## Config
- `ADMIN_IDS` — who may run `/stats`; when empty, `/stats` replies with the caller's id.

## Tests
- `tests/test_browse.py` — answer-before-Reservio, stale/garbage/out-of-window days, rate limits, group day view (slot links themselves: see [start-links](start-links.md)).
- `tests/test_routing.py` — private, group and fallback router filters; a forged `SlotCb` in a group never reaches a booking handler.

## Notes
- Booking is private-only, a security rule: a draft-order link works for anyone who sees it (`common.py:27`). In groups slot buttons are `t.me` deep links, so `slot_view` never runs for a group message.
- In a group the day message is shared: whoever switches the day or range changes it for everyone, in the tapper's language.
- `/days` is a hidden alias of `/start` and `/stats` is admin-only (`HIDDEN_COMMANDS`, `main.py`); `/stats` in a group is ignored silently.
