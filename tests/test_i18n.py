from __future__ import annotations

import pytest

from novariusirc.core.config import BotConfig
from novariusirc.core.i18n import (
    LANGUAGE_ENVIRONMENT,
    detect_environment_language,
    normalize_language,
    ntranslate,
    translate,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("de", "de"),
        ("de-DE", "de"),
        ("de_DE.UTF-8", "de"),
        ("ja_JP@calendar", "ja"),
        ("C.UTF-8", "en"),
        ("fr-FR", None),
    ],
)
def test_language_values_are_normalized(value: str, expected: str | None) -> None:
    assert normalize_language(value) == expected


def test_environment_language_uses_defined_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in LANGUAGE_ENVIRONMENT:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.setenv("LANGUAGE", "fr_FR:ja_JP")
    assert detect_environment_language() == "ja"

    monkeypatch.setenv("NOVARIUSIRC_LANG", "en_GB")
    assert detect_environment_language() == "en"


def test_gettext_catalogs_and_plural_rules_are_loaded() -> None:
    assert translate("Please slow down.", "de") == "Bitte langsamer."
    assert translate("Please slow down.", "ja") == "少し待ってから実行してください。"
    assert translate("Please slow down.", "en") == "Please slow down."
    singular = "Feeds: {count} active feed. Query: {query}"
    plural = "Feeds: {count} active feeds. Query: {query}"
    assert ntranslate(singular, plural, 1, "de", query="*") == (
        "Feeds: 1 aktiver Feed. Suche: *"
    )
    assert ntranslate(singular, plural, 2, "de", query="*") == (
        "Feeds: 2 aktive Feeds. Suche: *"
    )


def test_bot_language_accepts_locale_forms_and_rejects_unknown_languages() -> None:
    assert BotConfig(language="de_DE.UTF-8").language == "de"
    with pytest.raises(ValueError, match="unsupported bot language"):
        BotConfig(language="fr-FR")


def test_bot_language_default_comes_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in LANGUAGE_ENVIRONMENT:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("LC_MESSAGES", "ja_JP.UTF-8")
    assert BotConfig().language == "ja"
