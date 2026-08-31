"""Protocol-focused IRC transport and state primitives.

This internal package deliberately has no dependency on commands, roles,
plugins, feeds, or moderation.  NovariusIRC's bot layer consumes it through
the client adapter in :mod:`novariusirc.core.client`.
"""

from .capabilities import CapabilityProfile, CapabilityState, CapabilityToken
from .ctcp import CTCPMessage, format_ctcp, parse_ctcp
from .events import IRCEnvelope, IRCSource
from .protocol import IRCFeatures, IRCMessage, irc_casefold, parse_message
from .replies import ReplySeverity, StandardReply, parse_standard_reply
from .state import IRCState, IRCUser
from .transport import RateLimitedSender
from .wire import format_join, format_text_command, validate_raw_line

__all__ = [
    "CTCPMessage",
    "CapabilityProfile",
    "CapabilityState",
    "CapabilityToken",
    "IRCEnvelope",
    "IRCFeatures",
    "IRCMessage",
    "IRCSource",
    "IRCState",
    "IRCUser",
    "RateLimitedSender",
    "ReplySeverity",
    "StandardReply",
    "format_ctcp",
    "format_join",
    "format_text_command",
    "irc_casefold",
    "parse_ctcp",
    "parse_message",
    "parse_standard_reply",
    "validate_raw_line",
]
