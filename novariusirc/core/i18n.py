"""gettext-based localization for the core and built-in modules."""

from __future__ import annotations

import gettext
import os
from collections.abc import Callable
from pathlib import Path

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("de", "en", "ja")
LANGUAGE_ENVIRONMENT = (
    "NOVARIUSIRC_LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_MESSAGES",
    "LANG",
)
_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
_language = DEFAULT_LANGUAGE
_catalogs: dict[tuple[str, Path], gettext.NullTranslations] = {}


def normalize_language(value: str | None) -> str | None:
    """Map a locale or BCP-47 value to a supported language."""
    if not value:
        return None
    candidate = value.strip().split(":", 1)[0]
    candidate = candidate.split(".", 1)[0].split("@", 1)[0].replace("_", "-")
    primary = candidate.split("-", 1)[0].lower()
    if primary in {"c", "posix"}:
        return DEFAULT_LANGUAGE
    return primary if primary in SUPPORTED_LANGUAGES else None


def detect_environment_language() -> str:
    """Resolve the initial language from project and POSIX locale variables."""
    for variable in LANGUAGE_ENVIRONMENT:
        raw = os.getenv(variable, "")
        for candidate in raw.split(":"):
            language = normalize_language(candidate)
            if language:
                return language
    return DEFAULT_LANGUAGE


def _translation(
    language: str | None, locales_dir: Path | None = None
) -> gettext.NullTranslations:
    resolved = normalize_language(language) or DEFAULT_LANGUAGE
    directory = (locales_dir or _LOCALES_DIR).resolve()
    key = (resolved, directory)
    if key not in _catalogs:
        _catalogs[key] = gettext.translation(
            "novariusirc",
            localedir=directory,
            languages=[resolved],
            fallback=True,
        )
    return _catalogs[key]


def init_i18n(language: str, locales_dir: Path | None = None) -> Callable[[str], str]:
    """Set the process default while preserving explicit per-context lookup."""
    global _language
    _language = normalize_language(language) or DEFAULT_LANGUAGE
    return _translation(_language, locales_dir).gettext


def translate(message: str, language: str | None = None, **values: object) -> str:
    translated = _translation(language or _language).gettext(message)
    return translated.format(**values) if values else translated


def ntranslate(
    singular: str,
    plural: str,
    count: int,
    language: str | None = None,
    **values: object,
) -> str:
    translated = _translation(language or _language).ngettext(singular, plural, count)
    return translated.format(count=count, **values)


def gettext_lazy(message: str) -> str:
    """Compatibility alias for code that uses the process default language."""
    return translate(message)


__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGE_ENVIRONMENT",
    "SUPPORTED_LANGUAGES",
    "detect_environment_language",
    "gettext_lazy",
    "init_i18n",
    "normalize_language",
    "ntranslate",
    "translate",
]
