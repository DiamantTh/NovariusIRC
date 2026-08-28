"""Lightweight gettext wrapper."""

from __future__ import annotations

import gettext
from collections.abc import Callable
from pathlib import Path

_translator: gettext.NullTranslations | None = None
_language: str = "en"

_FALLBACK_TRANSLATIONS = {
    "de": {
        "pong": "pong",
        "uptime: {seconds}s": "Laufzeit: {seconds}s",
        "Commands ({prefix}):": "Befehle ({prefix}):",
        "Please slow down.": "Bitte langsamer.",
        "You are not allowed to run this command.": (
            "Du darfst diesen Befehl nicht ausführen."
        ),
        "Command failed.": "Befehl fehlgeschlagen.",
        "Usage: !rssfetch [limit]": "Nutzung: !rssfetch [limit]",
        "RSS/ATOM fetch triggered.": "RSS/ATOM-Abruf gestartet.",
        "Feeds are disabled.": "Feeds sind deaktiviert.",
        "Usage: !feed list [query]": "Nutzung: !feed list [query]",
        "No feeds matched your query.": "Keine Feeds passen zur Suche.",
        "Feeds: {count} active. Query: {query}": "Feeds: {count} aktiv. Suche: {query}",
        "New item": "Neuer Eintrag",
    },
    "ja": {
        "pong": "pong",
        "uptime: {seconds}s": "稼働時間: {seconds}s",
        "Commands ({prefix}):": "コマンド ({prefix}):",
        "Please slow down.": "少し待ってから実行してください。",
        "You are not allowed to run this command.": (
            "このコマンドを実行する権限がありません。"
        ),
        "Command failed.": "コマンドの実行に失敗しました。",
        "Usage: !rssfetch [limit]": "使い方: !rssfetch [limit]",
        "RSS/ATOM fetch triggered.": "RSS/ATOM 取得を開始しました。",
        "Feeds are disabled.": "フィードは無効です。",
        "Usage: !feed list [query]": "使い方: !feed list [query]",
        "No feeds matched your query.": "検索条件に一致するフィードはありません。",
        "Feeds: {count} active. Query: {query}": (
            "フィード: {count} 件が有効。検索: {query}"
        ),
        "New item": "新着項目",
    },
}


def init_i18n(language: str, locales_dir: Path | None = None) -> Callable[[str], str]:
    global _translator, _language
    _language = (language or "en").strip().lower()
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
        return _FALLBACK_TRANSLATIONS.get(_language, {}).get(message, message)
    translated = _translator.gettext(message)
    if translated != message:
        return translated
    return _FALLBACK_TRANSLATIONS.get(_language, {}).get(message, message)
