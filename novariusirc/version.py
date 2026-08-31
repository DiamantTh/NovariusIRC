"""Canonical NovariusIRC product, version, and embedded build information."""

from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Any

BOT_NAME = "NovariusIRC"
BOT_VERSION = "0.1.5"
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{7,40}")
_UTC_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _load_build_info() -> dict[str, Any]:
    try:
        content = files("novariusirc").joinpath("_build_info.json").read_text(
            encoding="utf-8"
        )
        data = json.loads(content)
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) and data.get("schema") == 1 else {}


def _format_native_version(build_info: dict[str, Any]) -> str:
    details: list[str] = []
    commit = build_info.get("commit")
    if isinstance(commit, str) and _COMMIT_PATTERN.fullmatch(commit):
        details.append(f"commit {commit[:12]}")
    built_at = build_info.get("built_at")
    if isinstance(built_at, str) and _UTC_TIMESTAMP_PATTERN.fullmatch(built_at):
        details.append(f"built {built_at}")

    native = f"{BOT_NAME} {BOT_VERSION}"
    return f"{native} ({'; '.join(details)})" if details else native


BUILD_INFO = _load_build_info()
NATIVE_VERSION = _format_native_version(BUILD_INFO)

__all__ = ["BOT_NAME", "BOT_VERSION", "BUILD_INFO", "NATIVE_VERSION"]
