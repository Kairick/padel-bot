# Bot views

**Purpose:** Telegram message texts and inline keyboards, plus the callback-data contracts that tie buttons to handlers.
**Code:** `padel_bot/bot/formatting.py`, `padel_bot/bot/keyboards.py`

## Interface
- Texts: `render_day`, `render_slot`, `render_notification`, `day_title`, `day_button_label`, `fmt_price`, `group_by_start`.
- Keyboards: `days_keyboard`, `day_keyboard`, `slot_keyboard`, `notification_keyboard`.
- Callback data: `DayCb` (`d`), `SlotCb` (`s`), `WatchDayCb` (`wh`), `WatchHourCb` (`wn`), `WatchCb` (`wt`), constants `NOOP`, `DAYS`, `WATCH`.
- Day codec and guard: `encode_day`, `decode_day`, `try_decode_day`, `parse_day` (rejects days outside the 7-day window), `normalize_range`, `RANGES`, `DEFAULT_RANGE`, `BOOKING_WINDOW_DAYS`.

## Owns
- Contracts: callback-data wire format (must stay under Telegram's 64-byte limit; changing it makes old buttons stale).
- Persistent / in-memory: nothing.

## Depends on
- [availability](availability.md) — `Availability` type.
- Shared `padel_bot/domain.py` (`TimeRange`, `WHOLE_DAY`, `Lang`), `padel_bot/bot/i18n.py` (texts), `padel_bot/reservio/models.py` (types).

## Config
- none

## Tests
- `tests/test_bot_views.py` — rendering ru/en, callback-data size limit, range button labels, day labels; notification rendering is covered in `tests/test_poller.py`.

## Notes
- Used by [browse](browse.md), [watch-ui](watch-ui.md) and `bot/common.py`. The monitor reaches the notification views only through the injected `watch.notification_message`.
- `parse_day` treats callback data as untrusted (it can be forged).
