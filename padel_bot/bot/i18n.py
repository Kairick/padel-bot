"""Bot texts in Russian and English. Language is picked from the Telegram client language."""

from typing import Literal

type Lang = Literal["ru", "en"]

DEFAULT_LANG: Lang = "en"
# Telegram language codes whose users most likely read Russian.
RUSSIAN_CODES = {"ru", "uk", "be", "kk"}

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
            "(Padel Port и Grand Padel) и даю ссылку на бронь.\n\nВыбери день 👇"
        ),
        "en": (
            "Hi! I show free padel courts in Batumi "
            "(Padel Port and Grand Padel) and give you a booking link.\n\nPick a day 👇"
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
            "Кнопка откроет оформление брони на <b>{time}</b>. "
            "Останется ввести контакты и подтвердить."
        ),
        "en": (
            "The button opens checkout for <b>{time}</b>. "
            "Just enter your contact details and confirm."
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
        "ru": (
            "Я работаю только в личных сообщениях, чтобы ссылки на бронь не достались другим. "
            "Напиши мне: {link}"
        ),
        "en": (
            "I only work in private chats, so booking links don't end up with others. "
            "Message me: {link}"
        ),
    },
    "private_only_short": {
        "ru": "Открой бота в личных сообщениях",
        "en": "Open the bot in a private chat",
    },
    "cmd_start": {"ru": "Выбрать день", "en": "Pick a day"},
    "cmd_today": {"ru": "Свободные корты сегодня", "en": "Free courts today"},
    "cmd_tomorrow": {"ru": "Свободные корты завтра", "en": "Free courts tomorrow"},
}


def detect_lang(language_code: str | None) -> Lang:
    if not language_code:
        return DEFAULT_LANG
    return "ru" if language_code.split("-")[0].lower() in RUSSIAN_CODES else "en"


def t(lang: Lang, key: str, **kwargs: object) -> str:
    text = TEXTS[key][lang]
    return text.format(**kwargs) if kwargs else text
