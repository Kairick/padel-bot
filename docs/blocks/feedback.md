# Feedback

**Purpose:** `/feedback` — forward a user's message (text, screenshot, album) to all admins with a sender line.
**Code:** `padel_bot/bot/feedback.py`

## Interface
- `/feedback <text>` — sends immediately; bare `/feedback` waits up to 10 min for the next non-command message; a photo captioned `/feedback` is the feedback itself.
- `on_message` (any non-command message in private) — consumes the wait and follows album parts.
- `deliver(message, bot, admin_ids)` — forwards to each admin, then replies with `sender_line`.

## Owns
- In-memory: `waiting` (user id -> waiting, TTL 600 s) and `albums` (media group -> first part's result, TTL 60 s) — module-level globals, lost on restart.
- External effects: Telegram messages to admins.
- Persistent: nothing (only a `feedback` counter in [stats](stats.md)).

## Depends on
- Telegram Bot API — `forward_message`, `send_message`.
- Shared `padel_bot/bot/common.py` — `private_router`, `lang_of`.
- [stats](stats.md) — `track_event("feedback")`.
- Shared `padel_bot/bot/throttle.py` — `feedback_limiter` (5/hour), injected by `main.py`.

## Config
- `ADMIN_IDS` — recipients; empty list makes `/feedback` answer "failed".

## Tests
- `tests/test_feedback.py` — inline/bare/captioned flows, rate limit, partial delivery, albums (ordering, cancellation, rejected first part), dispatcher-level race of two quick messages.

## Notes
- Concurrency rule: every decision is made before the handler's first `await` (`feedback.py:7`), because aiogram runs updates concurrently.
- Registered after `watch_router` and before `fallback_router`; its `NOT_COMMAND` catch-all must stay late in the order *(inferred)*.
- Sender line is Russian-only (admin-facing).
