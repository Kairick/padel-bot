# Padel Batumi Bot

Telegram-бот, который показывает свободные корты для падела в Батуми и даёт ссылку на бронирование.

Клубы: **Padel Port Batumi** (Padel Courts + Park Courts) и **Grand Padel Batumi**.

> Неофициальный проект. Не связан с Reservio и клубами. Данные берутся из публичного API страницы бронирования.

## Как работает

- Бот опрашивает публичный JSON:API Reservio `GET /v2/businesses/{businessId}/availability/booking-slots` по каждому корту параллельно.
- Результаты кэшируются в памяти на `CACHE_TTL_SECONDS` (по умолчанию 60 с). Одинаковые одновременные запросы схлопываются в один.
- «Игровой день» длится с 06:00 до 06:00, поэтому ночные слоты 00:00–01:00 показываются в предыдущем дне.
- Кнопка слота открывает список свободных кортов со ссылками на страницу брони Reservio.

Клубы и корты описаны в `venues.yaml`. ID услуг можно получить так:

```bash
uv run python scripts/dump_services.py padel-port-batumi2
```

## Локальный запуск

```bash
cp .env.example .env         # вписать BOT_TOKEN от @BotFather
uv sync
uv run padel-bot
```

Посмотреть слоты без Telegram:

```bash
uv run python scripts/show_slots.py tomorrow e   # m=утро, a=день, e=вечер, w=весь день
```

Тесты и линт:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Деплой на Fly.io

Бот работает через long polling, входящий порт не нужен.

```bash
fly launch --no-deploy --copy-config   # один раз
fly secrets set BOT_TOKEN=...
fly deploy
```

Для автодеплоя из GitHub добавь секрет `FLY_API_TOKEN` (`fly tokens create deploy`) и запусти workflow «Deploy to Fly.io».

Альтернатива: любой VPS с Docker.

```bash
docker build -t padel-bot .
docker run -d --restart unless-stopped --env-file .env padel-bot
```
