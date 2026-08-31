"""Command registration, authorization, and dispatch."""

from __future__ import annotations

import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from .i18n import ntranslate, translate

ROLE_ORDER = ("user", "admin", "owner")
CommandHandler = Callable[["CommandContext", list[str]], Awaitable[None] | None]


def _role_rank(role: str) -> int:
    try:
        return ROLE_ORDER.index(role)
    except ValueError:
        return 0


def _roles_satisfy(user_roles: Iterable[str], required: Iterable[str]) -> bool:
    required_roles = tuple(required)
    if not required_roles:
        return True
    if "owner" in user_roles:
        return True
    max_user = max((_role_rank(role) for role in user_roles), default=0)
    max_required = max((_role_rank(role) for role in required_roles), default=0)
    return max_user >= max_required


@dataclass
class CommandContext:
    nick: str
    hostmask: str
    channel: str | None
    message: str
    config: object
    client: object
    logger: logging.Logger
    roles: list[str]
    tags: dict[str, str | None] = field(default_factory=dict)
    account: str | None = None
    event: str = "PRIVMSG"
    server_time: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    async def reply(self, text: str) -> None:
        target = self.channel or self.nick
        await self.client.send_privmsg(target, text)

    @property
    def language(self) -> str:
        bot = getattr(self.config, "bot", None)
        return getattr(bot, "language", "en")

    def tr(self, message: str, **values: object) -> str:
        return translate(message, self.language, **values)

    def trn(
        self, singular: str, plural: str, count: int, **values: object
    ) -> str:
        return ntranslate(singular, plural, count, self.language, **values)

    def invocation(self, command: str) -> str:
        if self.channel:
            nick = getattr(self.client, "current_nick", None)
            if nick:
                return f"{nick}: {command}"
        bot = getattr(self.config, "bot", None)
        return f"{getattr(bot, 'prefix', '!')}{command}"


@dataclass(frozen=True)
class Command:
    name: str
    handler: CommandHandler
    roles: tuple[str, ...] = ("user",)
    help_text: str = ""
    aliases: tuple[str, ...] = ()
    owner: str | None = None


class CommandRegistry:
    def __init__(self, prefix: str = "!", rate_limit_seconds: float = 0.0):
        self.prefix = prefix
        self.rate_limit_seconds = max(0.0, rate_limit_seconds)
        self._commands: dict[str, Command] = {}
        self._primary_commands: dict[str, Command] = {}
        self._last_exec: dict[tuple[str, str], float] = {}

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = name.strip().lower()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError(f"Invalid command name: {name!r}")
        return normalized

    def register(
        self,
        name: str,
        handler: CommandHandler,
        roles: Sequence[str] = ("user",),
        help_text: str = "",
        aliases: Sequence[str] = (),
        owner: str | None = None,
    ) -> None:
        command_name = self._normalize_name(name)
        command_aliases = tuple(self._normalize_name(alias) for alias in aliases)
        invalid_roles = [role for role in roles if role not in ROLE_ORDER]
        if invalid_roles:
            raise ValueError(f"Unknown command roles: {', '.join(invalid_roles)}")
        all_names = (command_name, *command_aliases)

        if len(set(all_names)) != len(all_names):
            raise ValueError(f"Duplicate names declared for command {command_name!r}")
        collisions = [candidate for candidate in all_names if candidate in self._commands]
        if collisions:
            details = ", ".join(
                f"{candidate} (owner={self._commands[candidate].owner or 'unowned'})"
                for candidate in collisions
            )
            raise ValueError(
                f"Command name already registered: {details}; "
                f"incoming owner={owner or 'unowned'}"
            )

        command_entry = Command(
            name=command_name,
            handler=handler,
            roles=tuple(roles),
            help_text=help_text,
            aliases=command_aliases,
            owner=owner,
        )
        self._primary_commands[command_name] = command_entry
        for candidate in all_names:
            self._commands[candidate] = command_entry

    def unregister(self, name: str) -> bool:
        command_entry = self.get(name)
        if command_entry is None:
            return False
        self._primary_commands.pop(command_entry.name, None)
        for candidate in (command_entry.name, *command_entry.aliases):
            self._commands.pop(candidate, None)
        self._last_exec = {
            key: value
            for key, value in self._last_exec.items()
            if key[1] != command_entry.name
        }
        return True

    def unregister_owner(self, owner: str) -> None:
        names = [
            command_entry.name
            for command_entry in self._primary_commands.values()
            if command_entry.owner == owner
        ]
        for name in names:
            self.unregister(name)

    def get(self, name: str) -> Command | None:
        return self._commands.get(name.strip().lower())

    def list_commands(self, roles: Iterable[str] | None = None) -> list[Command]:
        commands: Iterable[Command] = self._primary_commands.values()
        if roles is not None:
            commands = (
                command_entry
                for command_entry in commands
                if _roles_satisfy(roles, command_entry.roles)
            )
        return sorted(commands, key=lambda item: item.name)

    def parse(self, message: str) -> tuple[str, list[str]] | None:
        if not message.startswith(self.prefix):
            return None
        parts = message[len(self.prefix) :].strip().split()
        if not parts:
            return None
        name, *args = parts
        return name.lower(), args

    async def dispatch(self, ctx: CommandContext) -> bool:
        parsed = self.parse(ctx.message)
        if parsed is None:
            return False
        name, args = parsed
        command_entry = self.get(name)
        if command_entry is None:
            return False

        if not _roles_satisfy(ctx.roles, command_entry.roles):
            await ctx.reply(ctx.tr("You are not allowed to run this command."))
            return True

        if self.rate_limit_seconds > 0:
            identity = ctx.hostmask.partition("!")[2] or ctx.nick
            key = (identity.lower(), command_entry.name)
            now = time.monotonic()
            last = self._last_exec.get(key, 0.0)
            if now - last < self.rate_limit_seconds:
                await ctx.reply(ctx.tr("Please slow down."))
                return True
            self._last_exec[key] = now

        try:
            result = command_entry.handler(ctx, args)
            if inspect.isawaitable(result):
                await result
        except Exception:
            ctx.logger.exception("Command %s failed", command_entry.name)
            await ctx.reply(ctx.tr("Command failed."))
        return True


def command(
    name: str | None = None,
    *,
    roles: Sequence[str] = ("user",),
    role: str | None = None,
    aliases: Sequence[str] = (),
    help_text: str = "",
) -> Callable[[CommandHandler], CommandHandler]:
    """Mark a plugin method for registration in the central registry."""

    required_roles = (role,) if role is not None else tuple(roles)

    def decorator(func: CommandHandler) -> CommandHandler:
        func.__dict__["__novarius_command__"] = {
            "name": name or func.__name__.removeprefix("cmd_"),
            "roles": required_roles,
            "aliases": tuple(aliases),
            "help_text": help_text or (func.__doc__ or "No description").strip(),
        }
        return func

    return decorator
