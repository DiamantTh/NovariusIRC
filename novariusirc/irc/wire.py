"""Safe construction of IRC wire lines."""

from __future__ import annotations


def validate_raw_line(message: str) -> str:
    """Validate one IRC line without its CRLF terminator."""
    if any(character in message for character in ("\r", "\n", "\0")):
        raise ValueError("IRC messages must not contain CR, LF, or NUL")
    if len(message.encode("utf-8")) > 510:
        raise ValueError("IRC message exceeds the 510-byte protocol limit")
    return message


def validate_target(target: str) -> str:
    """Reject target values that could alter IRC command framing."""
    if not target or any(
        character.isspace() or character in "\r\n\0:" for character in target
    ):
        raise ValueError(f"Invalid IRC target: {target!r}")
    return target


def truncate_utf8(value: str, maximum: int) -> str:
    """Truncate text without splitting a UTF-8 code point."""
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum:
        return value
    return encoded[:maximum].decode("utf-8", errors="ignore")


def format_text_command(command: str, target: str, message: str) -> str:
    """Build one safe PRIVMSG or NOTICE line."""
    if command not in {"PRIVMSG", "NOTICE"}:
        raise ValueError(f"Unsupported IRC text command: {command!r}")
    target = validate_target(target)
    clean_message = " ".join(message.replace("\0", "").splitlines()).strip()
    prefix = f"{command} {target} :"
    line = prefix + truncate_utf8(
        clean_message, 510 - len(prefix.encode("utf-8"))
    )
    return validate_raw_line(line)


def format_join(channel: str) -> str:
    """Build one safe JOIN line."""
    if (
        not channel
        or any(character.isspace() for character in channel)
        or any(character in channel for character in "\r\n\0,:")
    ):
        raise ValueError(f"Invalid IRC channel: {channel!r}")
    return validate_raw_line(f"JOIN {channel}")


def format_nick(nick: str) -> str:
    """Build a NICK registration line without accepting parameter injection."""
    return validate_raw_line(f"NICK {_validate_middle_parameter(nick, 'nickname')}")


def format_user(username: str, realname: str) -> str:
    """Build a USER registration line with a safe trailing real name."""
    username = _validate_middle_parameter(username, "username")
    if not realname or any(character in realname for character in "\r\n\0"):
        raise ValueError("Invalid IRC real name")
    return validate_raw_line(f"USER {username} 0 * :{realname}")


def _validate_middle_parameter(value: str, label: str) -> str:
    if (
        not value
        or value.startswith(":")
        or any(character.isspace() or character in "\r\n\0" for character in value)
    ):
        raise ValueError(f"Invalid IRC {label}: {value!r}")
    return value
