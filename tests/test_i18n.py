import pytest

from padel_bot.bot.i18n import MONTHS, TEXTS, WEEKDAYS_FULL, WEEKDAYS_SHORT, detect_lang, t


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("ru", "ru"),
        ("uk", "ru"),
        ("ka", "en"),
        ("pt-br", "en"),
        ("en", "en"),
        ("de", "en"),
        (None, "en"),
        ("", "en"),
    ],
)
def test_detect_lang(code, expected):
    assert detect_lang(code) == expected


def test_every_text_has_both_languages():
    for key, variants in TEXTS.items():
        assert set(variants) == {"ru", "en"}, key
        assert all(variants.values()), key


def test_calendar_names_complete():
    for lang in ("ru", "en"):
        assert len(WEEKDAYS_SHORT[lang]) == 7
        assert len(WEEKDAYS_FULL[lang]) == 7
        assert len(MONTHS[lang]) == 12


def test_format_placeholder():
    assert "checkout for <b>18:00</b>." in t("en", "booking_hint", time="18:00")
    assert "брони на <b>18:00</b>." in t("ru", "booking_hint", time="18:00")
