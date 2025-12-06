"""Command registry and dispatch."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

ROLE_ORDER = ("user", "admin", "owner")


def _role_rank(role: str) -> int:
    try:
        return ROLE_ORDER.index(role)
    except ValueError:
        return 0


def _roles_satisfy(user_roles: Iterable[str], required: Iterable[str]) -> bool:
    if not required:
        return True
    if "owner" in user_roles:
        return True
    max_user = max((_role_rank(r) for r in user_roles), default=0)
    max_required = max((_role_rank(r) for r in required), default=0)
    return max_user >= max_required


@dataclass
class CommandContext:
    nick: str
    channel: Optional[str]
    message: str
    config: object
    client: object
    logger: logging.Logger
    roles: List[str]

    async def reply(self, text: str) -> None:
        target = self.channel or self.nick
        await self.client.send_privmsg(target, text)


class Command:
    def __init__(
        self,
        name: str,
        handler: Callable[[CommandContext, List[str]], Awaitable[None]],
        roles: Tuple[str, ...] = ("user",),
        help_text: str = "",
    ):
        self.name = name
        self.handler = handler
        self.roles = roles
        self.help_text = help_text


class CommandRegistry:
    def __init__(self, prefix: str = "!"):
        self.prefix = prefix
        self._commands: Dict[str, Command] = {}

    def register(
        self,
        name: str,
        handler: Callable[[CommandContext, List[str]], Awaitable[None]],
        roles: Tuple[str, ...] = ("user",),
        help_text: str = "",
    ) -> None:
        self._commands[name] = Command(name=name, handler=handler, roles=roles, help_text=help_text)

    def get(self, name: str) -> Optional[Command]:
        return self._commands.get(name)

    def list_commands(self) -> List[Command]:
        return sorted(self._commands.values(), key=lambda c: c.name)

    def parse(self, message: str) -> Optional[Tuple[str, List[str]]]:
        if not message.startswith(self.prefix):
            return None
        without_prefix = message[len(self.prefix) :]
        parts = without_prefix.strip().split()
        if not parts:
            return None
        name, *args = parts
        return name.lower(), args

    async def dispatch(self, ctx: CommandContext) -> bool:
        parsed = self.parse(ctx.message)
        if not parsed:
            return False
        name, args = parsed
        command = self.get(name)
        if not command:
            return False
        if not _roles_satisfy(ctx.roles, command.roles):
            await ctx.reply("You are not allowed to run this command.")
            return True
        try:
            if asyncio.iscoroutinefunction(command.handler):
                await command.handler(ctx, args)
            else:
                command.handler(ctx, args)
        except Exception as exc:
            ctx.logger.error("Command %s failed: %s", name, exc)
            await ctx.reply("Command failed.")
        return True


def command(
    name: Optional[str] = None,
    roles: Tuple[str, ...] = ("user",),
    help_text: str = "",
) -> Callable[[Callable[[CommandContext, List[str]], Awaitable[None]]], Callable]:
    def decorator(func: Callable[[CommandContext, List[str]], Awaitable[None]]):
        cmd_name = name or func.__name__
        setattr(func, "__novarius_command__", {"name": cmd_name, "roles": roles, "help_text": help_text})
        return func

    return decorator
