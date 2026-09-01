"""Authentication helpers for SASL and NickServ."""

from __future__ import annotations

import base64
import fnmatch
import logging
from collections.abc import Callable

from novariusirc.irc.protocol import irc_casefold

from .config import AuthConfig, RolesConfig


def hostmask_match(
    pattern: str,
    hostmask: str,
    casefold: Callable[[str], str] = irc_casefold,
) -> bool:
    """Match hostmask against pattern with wildcards (* and ?).

    Examples:
        *!*@*.trusted.net matches anyone@*.trusted.net
        admin!*@* matches nick 'admin' from any host
        *!~user@host.tld matches any nick with ~user@host.tld
    """

    def normalize(value: str) -> str:
        nick, separator, userhost = value.partition("!")
        if not separator:
            return casefold(nick)
        # IRC CASEMAPPING applies to nicknames, not usernames or hostnames.
        # Those remain ASCII case-insensitive without RFC1459's []\^ aliases.
        return f"{casefold(nick)}!{userhost.lower()}"

    return fnmatch.fnmatchcase(normalize(hostmask), normalize(pattern))


class AuthManager:
    def __init__(
        self, auth_config: AuthConfig, roles: RolesConfig, logger: logging.Logger
    ):
        self.auth_config = auth_config
        self.roles_config = roles
        self.logger = logger
        self.casefold: Callable[[str], str] = irc_casefold

    def set_casefold(self, casefold: Callable[[str], str]) -> None:
        """Use the active server's CASEMAPPING for identity comparisons."""
        self.casefold = casefold

    def sasl_credentials(self) -> tuple[str, str] | None:
        if not self.auth_config.sasl_enabled:
            return None
        if not self.auth_config.sasl_username or not self.auth_config.sasl_password:
            return None
        return self.auth_config.sasl_username, self.auth_config.sasl_password

    def sasl_mechanism(self) -> str:
        mechanism = (self.auth_config.sasl_mechanism or "PLAIN").strip().upper()
        return mechanism or "PLAIN"

    def certfp_ready(self) -> bool:
        return bool(
            self.auth_config.certfp_enabled and self.auth_config.certfp_cert_file
        )

    def sasl_plain_payload(self) -> str | None:
        creds = self.sasl_credentials()
        if not creds:
            return None
        username, password = creds
        payload = f"{username}\0{username}\0{password}".encode()
        return base64.b64encode(payload).decode()

    def nickserv_credentials(self) -> tuple[str, str] | None:
        if not self.auth_config.nickserv_enabled:
            return None
        if (
            not self.auth_config.nickserv_username
            or not self.auth_config.nickserv_password
        ):
            return None
        return self.auth_config.nickserv_username, self.auth_config.nickserv_password

    def roles_for_hostmask(self, nick: str, hostmask: str) -> list[str]:
        """Determine roles for user based on hostmask pattern matching.

        Args:
            nick: User nickname for role lookup
            hostmask: Full hostmask nick!user@host

        Returns:
            List of roles (always includes 'user', may include 'admin', 'owner')
        """
        roles = ["user"]

        for admin in self.roles_config.admins:
            if hostmask_match(admin.hostmask, hostmask, self.casefold):
                roles.append("admin")
                break

        # Check owners
        for owner in self.roles_config.owners:
            if hostmask_match(owner.hostmask, hostmask, self.casefold):
                roles.append("owner")
                break

        return roles
