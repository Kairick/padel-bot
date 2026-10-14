# Key flows — sequence diagrams

Companion to [index.md](index.md) "Key flows": the same paths, as who-calls-whom in order.
Participants are blocks from the index; shared helpers (`bot/common.py`, `domain.py`) are omitted.

## User taps a time slot (main path)
```mermaid
sequenceDiagram
  actor U as User
  participant B as browse
  participant A as availability
  participant V as bot-views
  participant C as reservio-client
  participant R as Reservio
  U->>B: /start → day button (DayCb)
  B->>A: get_availability(day, range)
  A->>C: get_slots per service (cache 60 s, in-flight dedup)
  C->>R: GET slots
  R-->>C: slots
  A-->>B: Availability
  B->>V: render_day + day_keyboard
  B-->>U: day view with SlotCb buttons
  U->>B: time button (SlotCb)
  B-->>U: answer callback at once (limit 20/min)
  B->>A: booking_links(slots, user_id)
  A->>C: create_checkout_url per court (10 s cap)
  C->>R: booking page + GraphQL Order, SetTime
  R-->>C: draft order
  A-->>B: links (fallback: plain booking page)
  B->>V: render_slot + slot_keyboard
  B-->>U: courts with booking links
```

## Freed court notification (background path)
```mermaid
sequenceDiagram
  participant M as monitor
  participant S as subscriptions
  participant C as reservio-client
  participant W as watch-ui
  participant T as Telegram
  loop every MONITOR_INTERVAL_SECONDS, except 23:50–07:50
    M->>S: cleanup, has_subscriptions
    M->>C: get_slots per service, 8 days ahead
    M->>S: all, known_matches, poll_state
    M->>M: plan_cycle (pure)
    M->>S: apply_cycle (silent decisions)
    M->>W: render(freed times) — injected notification_message
    M->>T: send_message, one per chat
    alt sent
      M->>S: mark_notified
    else chat blocked / not found
      M->>S: delete_chat
    end
  end
```

## Monitor crash (edge path)
```mermaid
sequenceDiagram
  participant Main as main.serve
  participant M as monitor task
  participant P as polling task
  participant T as Telegram
  participant F as Fly.io
  Main->>P: start_polling
  Main->>M: wait for whichever ends first
  M--xMain: exception outside a cycle
  Main->>T: alert to every ADMIN_IDS chat
  Main->>P: cancel
  Main->>F: exit code 1 (MonitorCrashed)
  F->>Main: restart machine (on-failure, up to 10)
```
