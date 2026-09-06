"""Reloadable, time-bounded regular-expression rules for core moderation."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

import regex

MAX_RULE_FILE_BYTES = 1_048_576
MATCH_TIMEOUT_SECONDS = 0.05
URL_PATTERN = regex.compile(r"(?i)(?:https?://|www\.)[^\s<>\"']+")


class RegexRules:
    """Combine inline patterns with line-oriented files, reloading on change."""

    def __init__(
        self,
        patterns: Iterable[str],
        files: Iterable[str],
        logger: logging.Logger,
    ) -> None:
        self._inline = tuple(patterns)
        self._files = tuple(Path(path) for path in files)
        self._logger = logger
        self._fingerprints: tuple[tuple[str, int | None, int | None], ...] | None = None
        self._compiled: tuple[regex.Pattern, ...] = ()

    def _current_fingerprints(self) -> tuple[tuple[str, int | None, int | None], ...]:
        values = []
        for path in self._files:
            try:
                stat = path.stat()
                values.append((str(path), stat.st_mtime_ns, stat.st_size))
            except FileNotFoundError:
                values.append((str(path), None, None))
        return tuple(values)

    def _reload_if_needed(self) -> None:
        fingerprints = self._current_fingerprints()
        if fingerprints == self._fingerprints:
            return

        raw_patterns = list(self._inline)
        for path, _, size in fingerprints:
            source = Path(path)
            if size is None:
                self._logger.warning("Moderation rule file does not exist: %s", source)
                continue
            if size > MAX_RULE_FILE_BYTES:
                self._logger.warning("Ignoring oversized moderation rule file: %s", source)
                continue
            try:
                raw_patterns.extend(
                    line.strip()
                    for line in source.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                )
            except OSError as exc:
                self._logger.warning("Could not read moderation rule file %s: %s", source, exc)

        compiled = []
        for pattern in raw_patterns:
            try:
                compiled.append(regex.compile(pattern, regex.IGNORECASE))
            except regex.error as exc:
                self._logger.warning("Ignoring invalid moderation regex %r: %s", pattern, exc)
        self._compiled = tuple(compiled)
        self._fingerprints = fingerprints

    def matches(self, *values: str) -> bool:
        self._reload_if_needed()
        for pattern in self._compiled:
            for value in values:
                try:
                    if pattern.search(value, timeout=MATCH_TIMEOUT_SECONDS):
                        return True
                except TimeoutError:
                    self._logger.warning("Moderation regex timed out and was ignored: %r", pattern.pattern)
        return False


def extract_urls(text: str) -> list[tuple[str, str]]:
    """Return normalised URL and hostname pairs without making network requests."""
    found: list[tuple[str, str]] = []
    for match in URL_PATTERN.finditer(text, timeout=MATCH_TIMEOUT_SECONDS):
        raw = match.group().rstrip(".,;:!?)]}\"")
        parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
        hostname = (parsed.hostname or "").rstrip(".").lower()
        if not hostname:
            continue
        try:
            hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError:
            continue
        normalised = parsed._replace(scheme=parsed.scheme.lower(), netloc=hostname).geturl()
        found.append((normalised, hostname))
    return found
