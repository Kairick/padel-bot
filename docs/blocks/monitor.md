# Monitor

**Purpose:** Background loop that polls Reservio for all subscribed courts, decides which slots were freed, and notifies chats.
**Code:** `padel_bot/monitoring/matcher.py`, `padel_bot/monitoring/poller.py`

## Interface
- `Poller(bot, client, venues, store, interval_seconds, render=...).run()` — endless loop, started as an asyncio task by `main.py`; `render` (a `NotificationRenderer`) turns freed times into text + keyboard.
- `Poller.run_cycle() -> CycleOutcome` — one cycle: cleanup, fetch, plan, write, notify.
- `plan_cycle(...) -> CyclePlan` — pure decision function (no I/O, no clock); `FLAP_TIME`. The plan types live in [subscriptions](subscriptions.md).
- Pure helpers: `quiet_seconds`, `next_delay`.

## Owns
- External effects: Telegram notification messages; Reservio read load (one request per service per cycle, 8-day lookahead).
- Persistent: nothing directly — writes through [subscriptions](subscriptions.md) (`apply_cycle`, `mark_notified`, `delete_chat`, `cleanup`).
- In-memory: the loop itself (failure counter); one instance only.

## Depends on
- [reservio-client](reservio-client.md) — `get_slots`, `ReservioError.retry_after`.
- [subscriptions](subscriptions.md) — subscriptions, known matches, poll state, writes.
- [watch-ui](watch-ui.md) — `notification_message`, injected by `main.py` as `render`; the monitor imports nothing from `bot`.
- [availability](availability.md) — `court_slot`, `dedupe`.
- Shared `padel_bot/domain.py` — `TZ`, `current_play_day`.
- Telegram Bot API — `send_message`.

## Config
- `MONITOR_ENABLED` — start the loop (default true; subscription UI stays either way).
- `MONITOR_INTERVAL_SECONDS` — cycle interval, ≥ 60 (default 600) + up to 60 s jitter.

## Tests
- `tests/test_matcher.py` — freed-slot rule scenarios; `tests/test_poller.py` — silent first cycle, resend after failed send, merge per chat, unreachable chat, Retry-After, night sleep, 20-time cap.

## Notes
- Quiet hours 23:50–07:50 Batumi; backoff doubles to 1 h when every service fails; honours 429 `Retry-After`.
- "Freed" = seen busy before and inside the service's known horizon; slots that just entered the booking window and flaps < 30 min are not notified.
- A club is skipped for the cycle unless all its services answered.
- Notification is recorded only after a successful send; `TelegramForbiddenError` / "bot was blocked" deletes the chat's subscriptions.
- A crash outside a cycle ends the task; `main.serve` (`main.py:62`) then alerts admins and exits with code 1 so Fly restarts the machine (`on-failure`, 10 retries).
