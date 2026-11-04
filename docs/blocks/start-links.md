# Start links

**Purpose:** Turn a `/start` deep link from a group message back into its private screen: a slot's booking links or a day's subscription hour grid.
**Code:** `padel_bot/bot/start_links.py`

## Interface
- `start_links_router` — private chats only; included first by `main.py`, so browse's plain `/start` never sees a known link.
- `/start s_<day>_<rng>_<v>_<hm>` (`open_slot_link`) — slot view with booking links; bad or outdated link → welcome + day picker.
- `/start wh_<day>_<rng>` (`open_watch_link`) — hour grid of that day; bad or outdated link → `/watch`.

## Owns
- External effects: a slot link creates Reservio draft orders, through browse `slot_view`.
- In-memory: nothing; uses the injected `slot_limiter` (20/min, shared with slot taps).
- Stats: counts `slot_link` / `watch_link` (through [stats](stats.md) `track_event`).

## Depends on
- [browse](browse.md) — `slot_view`, `cmd_start` (fallback screen).
- [watch-ui](watch-ui.md) — `hours_view`, `cmd_watch` (fallback screen).
- [stats](stats.md) — `track_event`.
- [bot-views](bot-views.md) — `is_start_link`, `parse_start_link`, `parse_day`, `SlotCb`, `WatchDayCb`.
- Shared `padel_bot/bot/common.py` (`private_router`, `lang_of`), `padel_bot/domain.py`.

## Config
- none

## Tests
- `tests/test_browse.py` — slot links (round trip, bad links, rate limit) and which handler each `/start` reaches; `tests/test_watch.py` — Watch links; `tests/test_main.py` — router order.

## Notes
- The link parameter is client data and can be forged: the day goes through `parse_day`, the venue index is range-checked.
- Links are made by bot-views `start_link`; the two parts must stay in sync with the callback-data prefixes `s` and `wh`.
