# Padel Batumi Bot — план

## Контекст

В Батуми корты для падела бронируются через Reservio: Padel Port Batumi (padel-port-batumi2, две площадки — Padel Courts и Park Courts — в одном аккаунте) и Grand Padel Batumi (grandpadelbatumi).
Интерфейс Reservio неудобен: нужно открывать каждый корт отдельно, листать дни, не видно общей картины.
Цель — Telegram-бот, который по запросу («сегодня вечером», «завтра 18–21», «ближайшие 3 дня») показывает
свободные слоты по всем кортам всех клубов и даёт кликабельную ссылку на страницу бронирования.

Автобронирование в MVP не делаем (требует аккаунт Reservio в боте), оставляем как этап 2.

## Что выяснено про Reservio

- Сайт — Next.js, данные берёт из публичного JSON:API `https://api.reservio.com/v2/...` **без авторизации**.
- Слоты: `GET /v2/businesses/{businessId}/availability/booking-slots?filter[from]=YYYY-MM-DDTHH:MM:SS&filter[to]=...&filter[serviceId]={serviceId}&ignoreBookingBoundaries=1`
  - ответ: `data[].attributes.{start,end}` в ISO с `+04:00`, `relationships.resource.data.id`; `meta.total`, пагинация `page[limit]=50`.
  - есть также `/availability/booking-days` (какие дни вообще доступны) — для календаря.
- Справочник кортов (services) лежит в `__NEXT_DATA__` страницы `/services` (`initialApolloState`, ключи `Service:*`), либо можно захардкодить в конфиг.
- Один корт = одна «услуга» (service) длительностью 3540 с (59 мин), слоты шагом 1 час.
- `filter[from]`/`filter[to]` работают по датам (время игнорируется, `to` включительно), слоты в ответе не отсортированы. `ignoreBookingBoundaries` 0 и 1 дают одинаковый результат.
- Клубы работают до 02:00, поэтому бот использует «игровой день» 06:00–06:00: для дня D запрашиваются даты D и D+1.
- Grand Padel: каждая ценовая услуга отдаёт слоты только в своём интервале, их можно просто объединить в один корт.
- Ссылка на бронирование с выбранным временем (проверено на обоих клубах, без авторизации):
  1. `GET https://{subdomain}.reservio.com/booking?step=2&serviceId=...&resourceId=...` создаёт черновой заказ и редиректит на `/order?orderId=...&what=time`.
  2. `POST https://{subdomain}.reservio.com/api/graphql/booking-front`, запрос `bookingFrontByDomain(input:{domain}) { ... on Business { order(orderInput:{orderId}) { items { ... on AppointmentOrderItem { id } } } } }` отдаёт id позиции заказа.
  3. Мутация `setTimeToAppointmentOrderItem(input:{appointmentOrderItemId, businessId, orderId, time})`, где `time` это `start` слота в ISO.
  4. Ссылка пользователю: `/order?orderId=...&what=time`, дальше пользователь нажимает «Continue».
  - Ссылка сразу на `what=checkout` не годится. Для этого шага сервер не передаёт странице orderId, страница берёт его только из cookie `ORDER_ID`, а из URL записывает в cookie уже после первой отрисовки. Итог: при первом открытии в браузере без cookie для клуба 404, со второго раза работает. Cookie живёт сутки. Для `what=time` сервер orderId передаёт, 404 нет (проверено 2026-09-15).
  - Черновой заказ в состоянии INITIATED слот не держит, он остаётся свободным для других.
  - Если что-то не удалось, бот даёт прежнюю ссылку `/booking?step=2...` на выбор времени.
- Настройки бизнеса: TZ `Asia/Tbilisi`, `reservationsLaterThan=604800` (бронь максимум на 7 дней вперёд), `reservationsInAdvance=300` (минимум за 5 мин).

### Клубы

| Клуб | subdomain | businessId | Корты |
|---|---|---|---|
| Padel Port Batumi | padel-port-batumi2 | 1e32bd0a-0d5c-4e30-9788-ea488e713c4d | две площадки в одном аккаунте: Padel Court 1–4 и Park Court 1–2; 80 GEL/ч; часы 10:00–02:00 |
| Grand Padel Batumi | grandpadelbatumi | aac3b1f5-7e80-4052-bd09-adc7396cfbec | Court A (road side), Court B (sea side); каждый разбит на 3 услуги по цене: 08–13 → 50, 13–17 → 65, 17–02 → 80 GEL |

Service ID Padel Port: Court1 `6dcc4d1f-…`, Court2 `c36479d3-…`, Court3 `303f3adf-…`, Court4 `1dfea382-…`, Park1 `24481fd5-…`, Park2 `09922dde-…` (полные id — в `next_data.json` / положить в `venues.yaml`).
Grand Padel: 6 service id — вытащить тем же способом при реализации; в конфиге объединять услуги одного корта в один «корт» с ценой по интервалу.

## Язык и стек

**Python 3.14** — другой язык не даёт преимуществ: нагрузка минимальная, весь код — HTTP-запросы и форматирование,
а пользователь пишет на Python и будет сам его дорабатывать.

- `aiogram 3` — Telegram (async, inline-кнопки, FSM из коробки)
- `httpx` — async-клиент к Reservio
- `pydantic` / `pydantic-settings` — конфиг и модели
- `uv` — управление зависимостями (уже стоит)
- `pytest` + `respx` — тесты с замоканным Reservio
- `ruff` — линт/формат

## Структура проекта

```
padel-bot/
  pyproject.toml
  README.md
  PLAN.md
  .env.example           # BOT_TOKEN, CACHE_TTL_SECONDS (по умолчанию 60)
  venues.yaml            # клубы, businessId, корты → serviceId, цены
  Dockerfile
  padel_bot/
    __init__.py
    main.py              # запуск polling
    config.py            # Settings (pydantic-settings) + загрузка venues.yaml
    reservio/
      client.py          # ReservioClient.get_slots(business_id, service_id, from, to) -> list[Slot]
      models.py          # Venue, Court, Slot
      service.py         # get_availability(venues, date_from, date_to, hour_from, hour_to) -> AvailabilityTable (параллельно по всем кортам, asyncio.gather + кэш 60 с)
    bot/
      handlers.py        # /start, /today, /tomorrow, /week, кнопки дней, фильтр по времени
      keyboards.py       # inline-клавиатуры: выбор дня, «вечер/день/утро», кнопки-ссылки на бронь
      formatting.py      # рендер таблицы «время × корт» в HTML-сообщение
  tests/
    test_client.py       # парсинг ответа booking-slots (fixture из реального ответа)
    test_service.py      # объединение слотов по кортам, фильтр по часам, Grand Padel ценовые интервалы
    test_formatting.py
```

## UX бота (MVP)

1. `/start` → кнопки: **Сегодня**, **Завтра**, **Выбрать день** (7 дней вперёд), **Настройки времени**.
2. После выбора дня — фильтр по времени: **Утро (до 13)**, **День (13–17)**, **Вечер (17+)**, **Весь день**.
3. Ответ — одно сообщение на клуб (или одно общее), формат:

```
🎾 Padel Port Batumi — вт 15.09
18:00  Court 1 · Court 3 · Park 2
19:00  Court 1 · Court 2
20:00  —
21:00  Court 4
```

   Под сообщением inline-кнопки-ссылки: по одной на «слот × корт» (ограничить до ~8 кнопок, остальное — «показать ещё»),
   текст кнопки `18:00 Court 1 → 80 ₾`, url = booking-ссылка на этот корт.
4. Кнопка **Обновить** (перезапрос с игнорированием кэша).
5. Бот публичный, без whitelist пользователей.

## Этапы реализации

1. **Каркас**: `git init`, `gh auth switch -u Kairick`, `gh repo create kairick/padel-bot --public`, лицензия MIT, pyproject через `uv init` (`requires-python >=3.14`), ruff, README (пометка: неофициальный проект, не связан с Reservio и клубами), `.env.example`, `.gitignore`.
2. **Reservio-клиент**: `client.py` + модели, fixture из реального ответа, тест парсинга. Скрипт `scripts/dump_services.py` — вытаскивает services из `__NEXT_DATA__` любого поддомена и печатает YAML-фрагмент для `venues.yaml` (используется для Grand Padel и при появлении новых клубов).
3. **Сервис доступности**: параллельный опрос всех кортов за диапазон, объединение в таблицу `время → [корты]`, фильтр по часам, кэш в памяти с TTL 60 с (ключ: businessId+serviceId+дата; `cachetools.TTLCache`), дедупликация одновременных одинаковых запросов через общий `asyncio.Task`, обработка ошибок/таймаутов Reservio.
4. **Бот**: handlers + keyboards + formatting, polling. Проверить руками на реальных данных.
5. **Docker + деплой** (см. ниже), README с инструкцией запуска.
6. **Этап 2 (после MVP)**: подписка «сообщи, когда появится слот в пн вечером» (фоновый опрос раз в N минут); автобронирование через мутации `SetServiceAndResourceToAppointmentOrderItem` / `SetTimeToAppointmentOrderItem` (нужен логин на accounts.reservio.com — исследовать отдельно).

## Деплой

Бот работает в режиме long polling, нужен просто always-on процесс без входящего порта. Варианты:

| Вариант | Цена | Плюсы / минусы |
|---|---|---|
| **Fly.io** (рекомендую) | ~$0–2/мес за 1 shared-cpu VM | `fly launch` по Dockerfile, секреты через `fly secrets`, деплой одной командой; нужна карта |
| Railway | $5/мес hobby | ещё проще, деплой из GitHub-репо автоматом |
| Oracle Cloud Free Tier | бесплатно | всегда-бесплатная VM, но ручная настройка (docker compose + systemd), регистрация капризная |
| Hetzner CX22 | ~€4/мес | свой VPS, полный контроль; docker compose |
| Render free | бесплатно | background worker на free-плане недоступен — не подходит |

План: Dockerfile (python:3.14-slim + uv), `fly.toml`, GitHub Action на push в `main` → `flyctl deploy`. Если карту привязывать не хочется — Oracle Free Tier с docker compose, инструкция в README.

## Проверка

- `uv run pytest` — парсинг и агрегация на fixture.
- `uv run python -m padel_bot.reservio.service --date tomorrow` — CLI-дамп таблицы слотов с реального API (сверить с сайтом руками).
- Запустить бота локально с тестовым токеном от @BotFather, пройти сценарий «Завтра → Вечер → нажать кнопку → открылась страница брони нужного корта».
- После деплоя: бот отвечает, логи без ошибок Reservio.

## Статус

- 2026-09-14: MVP реализован (этапы 1–4), CI и Dockerfile готовы, публичный репо kairick/padel-bot.
- Осталось: живой прогон в Telegram с токеном, деплой на Fly.io (`fly launch`, `fly secrets set BOT_TOKEN=...`).
