"""Authentication helpers for SASL, NickServ, and TOTP sessions."""

from __future__ import annotations

import base64
import logging
import time
from typing import Dict, Optional, Tuple

import pyotp

from .config import AuthConfig, RolesConfig


class AuthSessionManager:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self.sessions: Dict[str, float] = {}

    def start(self, nick: str) -> None:
        self.sessions[nick.lower()] = time.time() + self.ttl_seconds

    def is_active(self, nick: str) -> bool:
        expires = self.sessions.get(nick.lower())
        if not expires:
            return False
        if expires < time.time():
            self.sessions.pop(nick.lower(), None)
            return False
        return True


class AuthManager:
    def __init__(self, auth_config: AuthConfig, roles: RolesConfig, logger: logging.Logger):
        self.auth_config = auth_config
        self.roles_config = roles
        self.logger = logger
        self.sessions = AuthSessionManager()

    def sasl_credentials(self) -> Optional[Tuple[str, str]]:
        if not self.auth_config.sasl_enabled:
            return None
        if not self.auth_config.sasl_username or not self.auth_config.sasl_password:
            return None
        return self.auth_config.sasl_username, self.auth_config.sasl_password

    def sasl_plain_payload(self) -> Optional[str]:
        creds = self.sasl_credentials()
        if not creds:
            return None
        username, password = creds
        payload = f"{username}\0{username}\0{password}".encode()
        return base64.b64encode(payload).decode()

    def nickserv_credentials(self) -> Optional[Tuple[str, str]]:
        if not self.auth_config.nickserv_enabled:
            return None
        if not self.auth_config.nickserv_username or not self.auth_config.nickserv_password:
            return None
        return self.auth_config.nickserv_username, self.auth_config.nickserv_password

    def verify_totp(self, code: str) -> bool:
        secret = self.auth_config.totp_secret
        if not secret:
            self.logger.warning("TOTP secret unavailable; cannot verify code")
            return False
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)

    def start_totp_session(self, nick: str, code: str) -> bool:
        if not self.verify_totp(code):
            return False
        self.sessions.start(nick)
        return True

    def roles_for_nick(self, nick: str) -> list[str]:
        roles = ["user"]
        lowered = nick.lower()
        if lowered in (adm.lower() for adm in self.roles_config.admins):
            roles.append("admin")
        for owner in self.roles_config.owners:
            if lowered == owner.nick.lower():
                if owner.require_totp and not self.sessions.is_active(nick):
                    break
                roles.append("owner")
        return roles
