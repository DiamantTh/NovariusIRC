"""IRC wire parsing and server-advertised protocol features."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

CASEMAPPINGS = {"ascii", "rfc1459", "rfc1459-strict", "strict-rfc1459"}
_ASCII_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ASCII_LOWER = "abcdefghijklmnopqrstuvwxyz"
_SERVER_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}):(\d{2})(\.\d+)?Z$")


def irc_casefold(value: str, mapping: str = "rfc1459") -> str:
    """Fold an IRC identifier according to the server's CASEMAPPING value."""
    if mapping not in CASEMAPPINGS:
        mapping = "rfc1459"
    source = _ASCII_UPPER
    target = _ASCII_LOWER
    if mapping in {"rfc1459", "rfc1459-strict", "strict-rfc1459"}:
        source += "[]\\"
        target += "{}|"
    if mapping == "rfc1459":
        source += "^"
        target += "~"
    return value.translate(str.maketrans(source, target))


def _unescape_tag(value: str) -> str:
    escapes = {":": ";", "s": " ", "\\": "\\", "r": "\r", "n": "\n"}
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value):
            index += 1
            result.append(escapes.get(value[index], value[index]))
        elif value[index] != "\\":
            result.append(value[index])
        index += 1
    return "".join(result)


def parse_server_time(value: str | None) -> datetime | None:
    """Parse an IRCv3 ``time`` tag, including an ISO-8601 leap second."""
    if value is None:
        return None
    match = _SERVER_TIME_RE.fullmatch(value)
    if match is None:
        return None
    date, hour_minute, second, fraction = match.groups()
    leap_second = second == "60"
    if int(second) > 60:
        return None
    normalized_second = "59" if leap_second else second
    normalized = f"{date}T{hour_minute}:{normalized_second}{fraction or ''}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if leap_second:
        parsed += timedelta(seconds=1)
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class IRCMessage:
    """A parsed IRC message including IRCv3 message tags."""

    command: str
    params: tuple[str, ...] = ()
    trailing: str | None = None
    prefix: str | None = None
    tags: dict[str, str | None] = field(default_factory=dict)


def parse_message(line: str) -> IRCMessage:
    """Parse one IRC protocol line and reject structurally invalid messages."""
    if not line or any(character in line for character in "\r\n\0"):
        raise ValueError("IRC message is empty or contains a forbidden character")

    encoded = line.encode()
    if line.startswith("@"):
        tag_section, separator, remainder = line.partition(" ")
        if not separator:
            raise ValueError("Malformed IRCv3 message tags")
        if len((tag_section + separator).encode()) > 8191:
            raise ValueError("IRCv3 message tags exceed 8191 bytes")
        if len(remainder.encode()) + 2 > 512:
            raise ValueError("IRC message body exceeds 512 bytes")
    elif len(encoded) + 2 > 512:
        raise ValueError("IRC message exceeds 512 bytes")

    rest = line
    tags: dict[str, str | None] = {}
    if rest.startswith("@"):
        tag_data, separator, rest = rest[1:].partition(" ")
        if not separator or not tag_data:
            raise ValueError("Malformed IRCv3 message tags")
        for item in tag_data.split(";"):
            key, equals, value = item.partition("=")
            if not key:
                raise ValueError("IRCv3 tag name must not be empty")
            tags[key] = _unescape_tag(value) if equals and value else None
        rest = rest.lstrip(" ")

    prefix: str | None = None
    if rest.startswith(":"):
        prefix, separator, rest = rest[1:].partition(" ")
        if not separator or not prefix:
            raise ValueError("Malformed IRC source prefix")
        rest = rest.lstrip(" ")

    head, marker, trailing = rest.partition(" :")
    parts = head.split()
    if not parts:
        raise ValueError("IRC message has no command")
    command, *params = parts
    if len(params) + bool(marker) > 15:
        raise ValueError("IRC message has more than 15 parameters")
    return IRCMessage(
        command=command.upper(),
        params=tuple(params),
        trailing=trailing if marker else None,
        prefix=prefix,
        tags=tags,
    )


@dataclass
class IRCFeatures:
    """Connection-specific values advertised through RPL_ISUPPORT (005)."""

    casemapping: str = "rfc1459"
    chantypes: str = "#&"
    prefix_modes: str = "ov"
    prefix_symbols: str = "@+"
    chanmodes: tuple[str, str, str, str] = ("b", "k", "l", "imnpst")
    statusmsg: str = ""
    network: str | None = None
    tokens: dict[str, str | None] = field(default_factory=dict)
    limits: dict[str, int] = field(default_factory=dict)
    target_limits: dict[str, int | None] = field(default_factory=dict)

    def casefold(self, value: str) -> str:
        return irc_casefold(value, self.casemapping)

    def is_channel(self, target: str) -> bool:
        return bool(target) and target[0] in self.chantypes

    def channel_from_target(self, target: str) -> str | None:
        candidate = target
        while candidate and candidate[0] in self.statusmsg:
            candidate = candidate[1:]
        return candidate if self.is_channel(candidate) else None

    def mode_for_prefix(self, prefix: str) -> str | None:
        try:
            return self.prefix_modes[self.prefix_symbols.index(prefix)]
        except (ValueError, IndexError):
            return None

    def prefix_for_mode(self, mode: str) -> str | None:
        try:
            return self.prefix_symbols[self.prefix_modes.index(mode)]
        except (ValueError, IndexError):
            return None

    def mode_takes_parameter(self, mode: str, adding: bool) -> bool:
        if mode in self.prefix_modes:
            return True
        type_a, type_b, type_c, _ = self.chanmodes
        return mode in type_a or mode in type_b or (adding and mode in type_c)

    def update(self, params: tuple[str, ...] | list[str]) -> None:
        """Apply the tokens from an RPL_ISUPPORT reply (excluding its text)."""
        # The first parameter is the client's nick, not an ISUPPORT token.
        for token in params[1:]:
            if token.startswith("-"):
                key = token[1:].upper()
                self.tokens.pop(key, None)
                if key == "CASEMAPPING":
                    self.casemapping = "rfc1459"
                elif key == "CHANTYPES":
                    self.chantypes = "#&"
                elif key == "PREFIX":
                    self.prefix_modes = "ov"
                    self.prefix_symbols = "@+"
                elif key == "CHANMODES":
                    self.chanmodes = ("b", "k", "l", "imnpst")
                elif key == "STATUSMSG":
                    self.statusmsg = ""
                elif key == "NETWORK":
                    self.network = None
                elif key == "TARGMAX":
                    self.target_limits.clear()
                self.limits.pop(key, None)
                continue
            key, equals, value = token.partition("=")
            key = key.upper()
            if not key:
                continue
            parsed_value = value if equals else None
            self.tokens[key] = parsed_value
            normalized_value = value.lower()
            if key == "CASEMAPPING" and normalized_value in CASEMAPPINGS:
                self.casemapping = normalized_value
            elif key == "CHANTYPES" and value:
                self.chantypes = value
            elif key == "PREFIX" and value.startswith("(") and ")" in value:
                modes, symbols = value[1:].split(")", 1)
                if (
                    modes
                    and len(modes) == len(symbols)
                    and len(set(modes)) == len(modes)
                    and len(set(symbols)) == len(symbols)
                ):
                    self.prefix_modes = modes
                    self.prefix_symbols = symbols
            elif key == "CHANMODES":
                groups = value.split(",")
                all_modes = "".join(groups)
                if len(groups) == 4 and len(set(all_modes)) == len(all_modes):
                    self.chanmodes = (groups[0], groups[1], groups[2], groups[3])
            elif key == "STATUSMSG":
                self.statusmsg = value
            elif key == "NETWORK" and value:
                self.network = value
            elif key in {
                "AWAYLEN",
                "CHANNELLEN",
                "HOSTLEN",
                "KICKLEN",
                "MODES",
                "NICKLEN",
                "TOPICLEN",
                "USERLEN",
            }:
                try:
                    self.limits[key] = int(value)
                except ValueError:
                    pass
            elif key == "TARGMAX":
                self.target_limits.clear()
                for item in value.split(","):
                    command, separator, maximum = item.partition(":")
                    if not separator or not command:
                        continue
                    try:
                        self.target_limits[command.upper()] = (
                            int(maximum) if maximum else None
                        )
                    except ValueError:
                        continue
