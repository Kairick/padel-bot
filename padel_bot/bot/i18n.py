"""Bot texts in Russian and English. Language is picked from the Telegram client language."""

from padel_bot.domain import Lang

WEEKDAYS_SHORT: dict[Lang, list[str]] = {
    "ru": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}
WEEKDAYS_FULL: dict[Lang, list[str]] = {
    "ru": ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
MONTHS: dict[Lang, list[str]] = {
    "ru": [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    ],
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
}  # fmt: skip

TEXTS: dict[str, dict[Lang, str]] = {
    "welcome": {
        "ru": (
            "Привет! Я показываю свободные корты для падела в Батуми "
            "(Padel Port и Grand Padel) и даю ссылку на бронь.\n\n"
            "Что-то не работает или чего-то не хватает? Напиши /feedback\n\nВыбери день 👇"
        ),
        "en": (
            "Hi! I show free padel courts in Batumi "
            "(Padel Port and Grand Padel) and give you a booking link.\n\n"
            "Something broken or missing? Send /feedback\n\nPick a day 👇"
        ),
    },
    "pick_day": {"ru": "Выбери день 👇", "en": "Pick a day 👇"},
    "today": {"ru": "Сегодня", "en": "Today"},
    "tomorrow": {"ru": "Завтра", "en": "Tomorrow"},
    "range_m": {"ru": "Утро", "en": "Morning"},
    "range_a": {"ru": "День", "en": "Afternoon"},
    "range_e": {"ru": "Вечер", "en": "Evening"},
    "range_w": {"ru": "Весь день", "en": "Whole day"},
    # Four filter buttons share one row, long labels get truncated by Telegram.
    "range_btn_m": {"ru": "Утро", "en": "Morning"},
    "range_btn_a": {"ru": "День", "en": "Day"},
    "range_btn_e": {"ru": "Вечер", "en": "Evening"},
    "range_btn_w": {"ru": "Все", "en": "All"},
    "venue_failed": {"ru": "не удалось получить расписание", "en": "couldn't load the schedule"},
    "venue_partial": {"ru": "часть кортов не ответила", "en": "some courts didn't respond"},
    "venue_no_slots": {"ru": "свободных слотов нет", "en": "no free slots"},
    "free_courts": {"ru": "Свободные корты:", "en": "Free courts:"},
    "booking_hint": {
        "ru": (
            "Кнопка откроет бронь на <b>{time}</b>. Нажми «Continue», введи контакты и подтверди."
        ),
        "en": (
            "The button opens the booking for <b>{time}</b>. "
            "Tap Continue, enter your contact details and confirm."
        ),
    },
    "other_day": {"ru": "📅 Другой день", "en": "📅 Other day"},
    "refresh": {"ru": "🔄 Обновить", "en": "🔄 Refresh"},
    "back": {"ru": "⬅️ Назад", "en": "⬅️ Back"},
    "refreshing": {"ru": "Обновляю…", "en": "Refreshing…"},
    "stale_button": {"ru": "Устаревшая кнопка", "en": "This button is outdated"},
    "slot_taken": {"ru": "Этот слот уже заняли 😕", "en": "This slot is already taken 😕"},
    "too_many_requests": {
        "ru": "Слишком часто 🙂 Подожди минуту и попробуй снова.",
        "en": "Too many taps 🙂 Wait a minute and try again.",
    },
    "stats_disabled": {
        "ru": (
            "Статистика выключена. Добавь ADMIN_IDS={user_id} в настройки бота и перезапусти его."
        ),
        "en": "Stats are disabled. Add ADMIN_IDS={user_id} to the bot settings and restart it.",
    },
    "private_only": {
        "ru": "Подписки и отзывы — только в личных сообщениях. Напиши мне: {link}",
        "en": "Subscriptions and feedback work only in a private chat. Message me: {link}",
    },
    "private_only_short": {
        "ru": "Открой бота в личных сообщениях",
        "en": "Open the bot in a private chat",
    },
    "watch_btn": {"ru": "🔔 Следить", "en": "🔔 Watch"},
    "watch_start": {
        "ru": "Выбери день и нажми 🔔 Следить 👇",
        "en": "Pick a day and tap 🔔 Watch 👇",
    },
    "watch_pick_hour": {"ru": "С какого часа следить?", "en": "Which hour should I watch?"},
    "watch_no_hours": {
        "ru": "На этот день следить уже поздно.",
        "en": "It's too late to watch this day.",
    },
    "watch_title": {"ru": "🔔 <b>Слежу за кортами</b>", "en": "🔔 <b>Watching for courts</b>"},
    "watch_any_club": {"ru": "Любой клуб", "en": "Any club"},
    "watch_courts_1": {"ru": "1 корт", "en": "1 court"},
    "watch_courts_2": {"ru": "2 корта", "en": "2 courts"},
    "watch_only_day": {"ru": "📅 Только {day}", "en": "📅 Only {day}"},
    "watch_delete": {"ru": "🗑 Удалить", "en": "🗑 Delete"},
    "watch_done": {"ru": "✓ Готово", "en": "✓ Done"},
    "watch_deleted": {"ru": "Подписка удалена", "en": "Subscription deleted"},
    "watch_duplicate": {"ru": "Такая подписка уже есть", "en": "You already have this one"},
    "watch_limit": {
        "ru": "Можно следить максимум за {limit}. Удали одну, чтобы добавить новую.",
        "en": "You can watch up to {limit}. Delete one to add a new one.",
    },
    "subs_title": {
        "ru": "🔔 <b>Подписки</b>\nНапишу, когда подходящий корт освободится.",
        "en": "🔔 <b>Subscriptions</b>\nI'll message you when a matching court is freed.",
    },
    "subs_empty": {
        "ru": (
            "Подписок пока нет. Выбери день и нажми 🔔 Следить, я напишу, когда корт освободится."
        ),
        "en": (
            "No subscriptions yet. Pick a day and tap 🔔 Watch, "
            "I'll message you when a court is freed."
        ),
    },
    "subs_new": {"ru": "➕ Новая подписка", "en": "➕ New subscription"},
    "notify_title": {"ru": "🔔 <b>Освободились корты</b>", "en": "🔔 <b>Courts are free</b>"},
    "notify_more": {"ru": "и ещё {count}", "en": "and {count} more"},
    "feedback_prompt": {
        "ru": (
            "Напиши одним сообщением, что не работает или чего не хватает. "
            "Можно приложить скриншот. Я передам разработчику."
        ),
        "en": (
            "Tell me in one message what's broken or missing. "
            "A screenshot is welcome. I'll pass it to the developer."
        ),
    },
    "feedback_thanks": {"ru": "Спасибо! Передал 🙌", "en": "Thanks! Passed it on 🙌"},
    "feedback_failed": {
        "ru": "Не получилось отправить 😕 Попробуй позже.",
        "en": "Couldn't send it 😕 Please try later.",
    },
    "feedback_too_many": {
        "ru": "Сообщений слишком много 🙂 Попробуй через час.",
        "en": "Too many messages 🙂 Try again in an hour.",
    },
    "cmd_start": {"ru": "Выбрать день", "en": "Pick a day"},
    "cmd_today": {"ru": "Свободные корты сегодня", "en": "Free courts today"},
    "cmd_tomorrow": {"ru": "Свободные корты завтра", "en": "Free courts tomorrow"},
    "cmd_watch": {"ru": "Следить за освободившимися кортами", "en": "Watch for freed courts"},
    "cmd_subs": {"ru": "Мои подписки", "en": "My subscriptions"},
    "cmd_feedback": {"ru": "Написать разработчику", "en": "Message the developer"},
}

# "Every Monday" as a whole phrase: Russian changes the word by gender.
WEEKLY: dict[Lang, list[str]] = {
    "ru": [
        "Каждый понедельник", "Каждый вторник", "Каждую среду", "Каждый четверг",
        "Каждую пятницу", "Каждую субботу", "Каждое воскресенье",
    ],
    "en": [
        "Every Monday", "Every Tuesday", "Every Wednesday", "Every Thursday",
        "Every Friday", "Every Saturday", "Every Sunday",
    ],
}  # fmt: skip


def t(lang: Lang, key: str, **kwargs: object) -> str:
    text = TEXTS[key][lang]
    return text.format(**kwargs) if kwargs else text
