"""Parsing and formatting for single-frame CTCP messages."""

from __future__ import annotations

from dataclasses import dataclass

_DELIMITER = "\x01"


@dataclass(frozen=True)
class CTCPMessage:
    command: str
    parameters: str = ""


def parse_ctcp(message: str) -> CTCPMessage | None:
    """Return a CTCP message only when the entire IRC text is one frame."""
    if not (message.startswith(_DELIMITER) and message.endswith(_DELIMITER)):
        return None
    body = message[1:-1]
    if not body or _DELIMITER in body or any(char in body for char in "\r\n\0"):
        return None
    command, separator, parameters = body.partition(" ")
    if not command.isascii() or not command.isalnum():
        return None
    return CTCPMessage(command.upper(), parameters if separator else "")


def format_ctcp(command: str, parameters: str = "") -> str:
    """Build one CTCP frame suitable for PRIVMSG or NOTICE text."""
    normalized = command.strip().upper()
    if not normalized.isascii() or not normalized.isalnum():
        raise ValueError(f"Invalid CTCP command: {command!r}")
    clean_parameters = " ".join(parameters.replace("\0", "").splitlines()).strip()
    if _DELIMITER in clean_parameters:
        raise ValueError("CTCP parameters must not contain the CTCP delimiter")
    body = normalized if not clean_parameters else f"{normalized} {clean_parameters}"
    return f"{_DELIMITER}{body}{_DELIMITER}"
