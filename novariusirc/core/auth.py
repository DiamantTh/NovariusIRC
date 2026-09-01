"""Authentication helpers for SASL and NickServ."""

from __future__ import annotations

import base64
import fnmatch
import logging
from collections.abc import Callable

from novariusirc.irc.protocol import irc_casefold

from .config import AuthConfig, RolesConfig
from .database import RoleBinding


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
        self,
        auth_config: AuthConfig,
        roles: RolesConfig,
        logger: logging.Logger,
        persistent_bindings: list[RoleBinding] | None = None,
    ):
        self.auth_config = auth_config
        self.roles_config = roles
        self.logger = logger
        self.casefold: Callable[[str], str] = irc_casefold
        self._persistent_bindings = persistent_bindings

    def set_casefold(self, casefold: Callable[[str], str]) -> None:
        """Use the active server's CASEMAPPING for identity comparisons."""
        self.casefold = casefold

    @staticmethod
    def certfp_from_tags(tags: dict[str, str | None]) -> str | None:
        """Return a certificate fingerprint from commonly used IRCv3 tags."""
        for name in ("certfp", "solanum.chat/certfp"):
            value = tags.get(name)
            if value:
                return value
        return None

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

    def set_persistent_bindings(self, bindings: list[RoleBinding]) -> None:
        """Replace the authorization cache after a role-management change."""
        self._persistent_bindings = bindings

    def roles_for_hostmask(self, nick: str, hostmask: str) -> list[str]:
        """Compatibility wrapper for callers without IRCv3 identity metadata."""
        return self.roles_for_identity(nick, hostmask)

    def roles_for_identity(
        self,
        nick: str,
        hostmask: str,
        *,
        account: str | None = None,
        certfp: str | None = None,
    ) -> list[str]:
        """Determine roles from configured fallback or persistent bindings.

        Args:
            nick: User nickname for role lookup
            hostmask: Full hostmask nick!user@host

        Returns:
            List of roles (always includes 'user', may include 'admin', 'owner')
        """
        roles = ["user"]

        if self._persistent_bindings is not None:
            for binding in self._persistent_bindings:
                if binding.binding_type == "hostmask" and hostmask_match(
                    binding.binding_value, hostmask, self.casefold
                ):
                    roles.append(binding.role_name)
                elif binding.binding_type == "account" and account and account != "0":
                    if binding.binding_value.casefold() == account.casefold():
                        roles.append(binding.role_name)
                elif (
                    binding.binding_type == "certfp"
                    and certfp
                    and binding.binding_value == certfp.replace(":", "").lower()
                ):
                    roles.append(binding.role_name)
            return list(dict.fromkeys(roles))

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
