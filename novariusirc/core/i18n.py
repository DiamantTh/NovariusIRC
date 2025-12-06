"""Lightweight gettext wrapper."""

from __future__ import annotations

import gettext
from pathlib import Path
from typing import Callable, Optional

_translator: Optional[gettext.NullTranslations] = None


def init_i18n(language: str, locales_dir: Optional[Path] = None) -> Callable[[str], str]:
    global _translator
    localedir = locales_dir or Path(__file__).resolve().parent.parent / "locales"
    _translator = gettext.translation(
        "novariusirc",
        localedir=localedir,
        languages=[language],
        fallback=True,
    )
    return _translator.gettext


def gettext_lazy(message: str) -> str:
    if _translator is None:
        return message
    return _translator.gettext(message)
