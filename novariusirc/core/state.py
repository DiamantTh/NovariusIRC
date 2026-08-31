"""Compatibility imports for the internal IRC state package.

New code should import from :mod:`novariusirc.irc.state`.
"""

from novariusirc.irc.state import (
    IRCChannel,
    IRCMembership,
    IRCState,
    IRCUser,
    normalize_account,
    split_source,
)

__all__ = [
    "IRCChannel",
    "IRCMembership",
    "IRCState",
    "IRCUser",
    "normalize_account",
    "split_source",
]
