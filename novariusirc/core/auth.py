"""Authentication helpers for SASL, NickServ, and TOTP sessions."""

from __future__ import annotations

import base64
import fnmatch
import logging
import time
from collections.abc import Callable

import pyotp

from .config import AuthConfig, RolesConfig
from .protocol import irc_casefold


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


class AuthSessionManager:
    def __init__(
        self,
        ttl_seconds: int = 1800,
        casefold: Callable[[str], str] = irc_casefold,
    ):
        self.ttl_seconds = ttl_seconds
        self.casefold = casefold
        self.sessions: dict[str, float] = {}

    def start(self, nick: str) -> None:
        self.sessions[self.casefold(nick)] = time.time() + self.ttl_seconds

    def is_active(self, nick: str) -> bool:
        key = self.casefold(nick)
        expires = self.sessions.get(key)
        if not expires:
            return False
        if expires < time.time():
            self.sessions.pop(key, None)
            return False
        return True

    def end(self, nick: str) -> bool:
        """End auth session for nick. Returns True if session existed."""
        return self.sessions.pop(self.casefold(nick), None) is not None

    def rename(self, old_nick: str, new_nick: str) -> None:
        expires = self.sessions.pop(self.casefold(old_nick), None)
        if expires and expires >= time.time():
            self.sessions[self.casefold(new_nick)] = expires


class AuthManager:
    def __init__(
        self, auth_config: AuthConfig, roles: RolesConfig, logger: logging.Logger
    ):
        self.auth_config = auth_config
        self.roles_config = roles
        self.logger = logger
        self.casefold: Callable[[str], str] = irc_casefold
        self.sessions = AuthSessionManager(
            ttl_seconds=auth_config.session_timeout_seconds,
            casefold=self.casefold,
        )

    def set_casefold(self, casefold: Callable[[str], str]) -> None:
        """Use the active server's CASEMAPPING for identity comparisons."""
        if self.sessions.sessions:
            self.logger.info("Clearing TOTP sessions after CASEMAPPING change")
            self.sessions.sessions.clear()
        self.casefold = casefold
        self.sessions.casefold = casefold

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

    def verify_totp(self, code: str, secret: str | None = None) -> bool:
        """Verify TOTP code against secret with configured parameters.

        Args:
            code: TOTP code to verify
            secret: Optional specific secret (uses global if not provided)

        TOTP Parameters (RFC 6238):
            digest: sha1 (legacy), sha256, sha512
            digits: 6 (standard) or 8 (higher security)
            interval: 30 seconds (standard)
            valid_window: configured interval tolerance (±4 intervals by default)
        """
        secret = secret or self.auth_config.totp_secret
        if not secret:
            self.logger.warning("TOTP secret unavailable; cannot verify code")
            return False

        totp = pyotp.TOTP(
            secret,
            digits=self.auth_config.totp_digits,
            digest=self.auth_config.totp_digest,
            interval=self.auth_config.totp_interval,
        )
        return totp.verify(code, valid_window=self.auth_config.totp_valid_window)

    def start_totp_session(self, nick: str, code: str, hostmask: str = "") -> bool:
        """Start TOTP session if code is valid for user's secret.

        Args:
            nick: User nickname (for session tracking)
            code: TOTP code
            hostmask: User hostmask for secret lookup
        """
        # Find user-specific secret if hostmask provided
        user_secret = None
        if hostmask:
            # Check owners first
            for owner in self.roles_config.owners:
                if (
                    hostmask_match(owner.hostmask, hostmask, self.casefold)
                    and owner.totp_secret
                ):
                    user_secret = owner.totp_secret
                    break
            # Check admins if not found
            if not user_secret:
                for admin in self.roles_config.admins:
                    if (
                        hostmask_match(admin.hostmask, hostmask, self.casefold)
                        and admin.totp_secret
                    ):
                        user_secret = admin.totp_secret
                        break

        if not self.verify_totp(code, secret=user_secret):
            return False
        self.sessions.start(nick)
        return True

    def end_totp_session(self, nick: str) -> bool:
        """End TOTP session for nick. Returns True if session existed."""
        return self.sessions.end(nick)

    def rename_nick(self, old_nick: str, new_nick: str) -> None:
        self.sessions.rename(old_nick, new_nick)

    def roles_for_hostmask(self, nick: str, hostmask: str) -> list[str]:
        """Determine roles for user based on hostmask pattern matching.

        Args:
            nick: User nickname (for TOTP session tracking)
            hostmask: Full hostmask nick!user@host

        Returns:
            List of roles (always includes 'user', may include 'admin', 'owner')
        """
        roles = ["user"]

        # Check admins (with optional TOTP)
        for admin in self.roles_config.admins:
            if hostmask_match(admin.hostmask, hostmask, self.casefold):
                if admin.require_totp and not self.sessions.is_active(nick):
                    self.logger.debug(
                        "Admin %s matched but requires TOTP auth", hostmask
                    )
                    break
                roles.append("admin")
                break

        # Check owners
        for owner in self.roles_config.owners:
            if hostmask_match(owner.hostmask, hostmask, self.casefold):
                if owner.require_totp and not self.sessions.is_active(nick):
                    self.logger.debug(
                        "Owner %s matched but requires TOTP auth", hostmask
                    )
                    break
                roles.append("owner")
                break

        return roles
