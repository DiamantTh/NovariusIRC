"""Protocol-focused IRC transport and state primitives.

This internal package deliberately has no dependency on commands, roles,
plugins, feeds, or moderation.  NovariusIRC's bot layer consumes it through
the client adapter in :mod:`novariusirc.core.client`.
"""

from .capabilities import CapabilityState, CapabilityToken
from .protocol import IRCFeatures, IRCMessage, irc_casefold, parse_message
from .state import IRCState, IRCUser

__all__ = [
    "CapabilityState",
    "CapabilityToken",
    "IRCFeatures",
    "IRCMessage",
    "IRCState",
    "IRCUser",
    "irc_casefold",
    "parse_message",
]
