"""Compatibility imports for the internal IRC protocol package.

New code should import from :mod:`novariusirc.irc.protocol`.
"""

from novariusirc.irc.protocol import (
    CASEMAPPINGS,
    IRCFeatures,
    IRCMessage,
    irc_casefold,
    parse_message,
    parse_server_time,
)

__all__ = [
    "CASEMAPPINGS",
    "IRCFeatures",
    "IRCMessage",
    "irc_casefold",
    "parse_message",
    "parse_server_time",
]
