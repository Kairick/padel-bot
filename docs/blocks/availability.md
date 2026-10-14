# Availability

**Purpose:** Free slots across all configured venues for one play day, with a TTL cache, request de-duplication, and per-user cached booking links.
**Code:** `padel_bot/reservio/service.py`

## Interface
- `AvailabilityService.get_availability(day, time_range=WHOLE_DAY, force_refresh=False) -> Availability` — fetches every venue/court/service in parallel, filters past slots and the hour range, dedupes, sorts.
- `AvailabilityService.booking_links(slots, user_id, wait_seconds=10) -> list[str]` — one checkout link per slot; falls back to `CourtSlot.booking_url` on failure or timeout.
- `AvailabilityService.venues` — the venue list, read by bot handlers as the source of truth.
- `Availability` (`day`, `slots`, `failed_venues`, `by_venue()`).
- `court_slot(...)`, `dedupe(...)` — slot assembly helpers, also used by the monitor.

## Owns
- In-memory: slot cache `TTLCache` keyed `(business_id, service_id, day)` (TTL `CACHE_TTL_SECONDS`); in-flight fetch tasks; link cache keyed per Telegram user (10 min); in-flight link tasks.
- External effects: Reservio draft orders, via [reservio-client](reservio-client.md).

## Depends on
- [reservio-client](reservio-client.md) — `get_slots`, `create_checkout_url`.
- Shared `padel_bot/domain.py` — `TZ`, `TimeRange`, `WHOLE_DAY`.

## Config
- `CACHE_TTL_SECONDS` — slot cache TTL (default 60).

## Tests
- `tests/test_service.py` (merge, hour filter, Grand Padel multi-service courts), `tests/test_booking_links.py` (per-user links, timeout fallback).

## Notes
- Links are never shared between users: two people must not land in the same draft order.
- A slow draft keeps running after the timeout and lands in the cache for the next tap.
- Asks Reservio for `day..day+1` because the play day spills past midnight.
- All caches are per process: correct only with one instance (fly.toml pins one machine).
