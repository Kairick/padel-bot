# Reservio client

**Purpose:** HTTP access to Reservio: read free slots of a service, create a draft order with the time preselected.
**Code:** `padel_bot/reservio/client.py`

## Interface
- `ReservioClient.get_slots(business_id, service_id, date_from, date_to) -> list[RawSlot]` — paginated `GET /v2/businesses/{id}/availability/booking-slots` (JSON:API, no auth); `date_to` inclusive.
- `ReservioClient.create_checkout_url(subdomain, business_id, service_id, resource_id, start) -> str` — `GET https://<sub>.reservio.com/booking?step=2` (redirect carries `orderId`), then GraphQL `Order` query + `SetTime` mutation; returns `/order?orderId=...&what=time`.
- `ReservioError(message, retry_after)` — every failure is wrapped in it; `retry_after` set on HTTP 429.
- `parse_retry_after`, `parse_slot` — pure helpers (tested directly).
- `aclose()` — closes the shared `httpx.AsyncClient`.

## Owns
- External effects: creates Reservio draft orders (one per `create_checkout_url` call; a draft does not hold the slot).
- Contracts: Reservio wire formats (JSON:API slot items, booking-front GraphQL queries) live only here.

## Depends on
- Reservio public API (`api.reservio.com`) and per-club booking front (`<subdomain>.reservio.com`).
- Shared types `RawSlot` from `padel_bot/reservio/models.py`.

## Config
- `RESERVIO_API_URL` — base URL, default `https://api.reservio.com` (*(inferred)* env name from the `reservio_api_url` settings field; not in `.env.example`).

## Tests
- `tests/test_client.py` — slot parsing on a real-response fixture (`tests/fixtures/booking_slots_padel_port.json`), pagination, 429/Retry-After, checkout flow via `respx`.

## Notes
- Timeout 15 s, fixed User-Agent pointing at the GitHub repo.
- The checkout link deliberately opens the time step, not `what=checkout` (404 without cookie) — see docstring at `client.py:94`.
- One client instance is shared by the availability service and the monitor (wired in `main.py`).
