# Bot views

**Purpose:** Telegram message texts and inline keyboards, plus the callback-data and deep-link contracts that tie buttons to handlers.
**Code:** `padel_bot/bot/formatting.py`, `padel_bot/bot/keyboards.py`

## Interface
- Texts: `render_day` (date title only; the range shows as a ✓ on its button), `render_slot`, `render_notification`, `day_title`, `day_button_label`, `fmt_price`, `group_by_start`.
- Keyboards: `days_keyboard`, `day_keyboard`, `slot_keyboard`, `notification_keyboard`.
- `day_keyboard(..., bot_username=None)` — ranges row; per club a header row (`Venue.short_label`) and its times; «Подписка» row; «Дата» + «Обновить» row. With `bot_username` (group mode) slot and Watch buttons become `start_link` URL buttons and times go 3 per row instead of 4.
- Deep links: `start_link` (callback data → `t.me/<bot>?start=...`, `:` → `_`), `parse_start_link`, `is_start_link` (magic filter for `CommandStart`).
- Callback data: `DayCb` (`d`), `SlotCb` (`s`), `WatchDayCb` (`wh`), `WatchHourCb` (`wn`), `WatchCb` (`wt`), constants `NOOP`, `DAYS`, `WATCH`.
- Day codec and guard: `encode_day`, `decode_day`, `try_decode_day`, `parse_day` (rejects days outside the 7-day window), `normalize_range`, `RANGES`, `DEFAULT_RANGE`, `BOOKING_WINDOW_DAYS`.

## Owns
- Contracts: callback-data wire format (under Telegram's 64-byte limit; changing it makes old buttons stale). `SlotCb` and `WatchDayCb` are also `/start` parameters of group links (same limit, only `[A-Za-z0-9_-]`).
- Persistent / in-memory: nothing.

## Depends on
- [availability](availability.md) — `Availability` type.
- Shared `padel_bot/domain.py` (`TimeRange`, `WHOLE_DAY`, `Lang`), `padel_bot/bot/i18n.py` (texts), `padel_bot/reservio/models.py` (types).

## Config
- none (club short names come from `venues.yaml` `short_name`).

## Tests
- `tests/test_bot_views.py` — rendering ru/en, callback-data size limit, last rows' labels, group mode (URL buttons, 3 per row), club short names, day labels; notification rendering is covered in `tests/test_poller.py`.

## Notes
- Layout decisions (owner, 2026-11-03): nav labels are plain text and split over two rows — three labels, or emoji, didn't fit phones and narrow group chats; URL buttons get a Telegram arrow, hence 3 times per row in groups. `answerCallbackQuery(url=...)` instead of URL buttons was tried and opens the browser on iOS.
- Used by [browse](browse.md), [watch-ui](watch-ui.md) and `bot/common.py`. The monitor reaches the notification views only through the injected `watch.notification_message`.
- `parse_day` and `parse_start_link` treat client data as untrusted (it can be forged).
