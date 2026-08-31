"""Canonical NovariusIRC product, version, and embedded build information."""

from __future__ import annotations

import json
import platform
import re
import socket
import ssl
from importlib.resources import files
from importlib.util import find_spec
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
SIMPLE_VERSION = f"{BOT_NAME} {BOT_VERSION}"
NATIVE_VERSION = _format_native_version(BUILD_INFO)


def _module_available(module: str) -> bool:
    try:
        return find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def detailed_version() -> str:
    """Return local runtime diagnostics without instance configuration."""
    features = ["TLS", "IRCv3", "SASL", "Unix control", "process workers"]
    if socket.has_ipv6:
        features.insert(0, "IPv6")
    optional = (
        f"uvloop={'yes' if _module_available('uvloop') else 'no'}, "
        f"journald={'yes' if _module_available('systemd.journal') else 'no'}"
    )
    runtime = (
        f"Runtime: {platform.python_implementation()} "
        f"{platform.python_version()}, {ssl.OPENSSL_VERSION}"
    )
    return "\n".join(
        (
            NATIVE_VERSION,
            runtime,
            f"Features: {', '.join(features)}",
            f"Optional: {optional}",
        )
    )

__all__ = [
    "BOT_NAME",
    "BOT_VERSION",
    "BUILD_INFO",
    "NATIVE_VERSION",
    "SIMPLE_VERSION",
    "detailed_version",
]
