"""Local, Unix-socket based access to registered bot commands."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import stat
from collections.abc import Awaitable, Callable
from pathlib import Path

from novariusirc.core.commands import CommandContext, CommandRegistry
from novariusirc.core.config import Config

Output = Callable[[str], Awaitable[None] | None]


class LocalCommandClient:
    """Minimal client adapter for local command replies."""

    def __init__(self, output: Output | None = None):
        self.messages: list[str] = []
        self.output = output

    async def send_privmsg(self, target: str, message: str) -> None:
        self.messages.append(message)
        if self.output:
            result = self.output(message)
            if inspect.isawaitable(result):
                await result


async def dispatch_local_command(
    commands: CommandRegistry,
    config: Config,
    logger: logging.Logger,
    client: LocalCommandClient,
    line: str,
) -> bool:
    """Run one local owner command; return false for an exit request."""
    line = line.strip()
    if line.lower() in {"exit", "quit"}:
        return False
    if not line:
        return True
    message = line if line.startswith(config.bot.prefix) else f"{config.bot.prefix}{line}"
    context = CommandContext(
        nick="local",
        hostmask="local!unix-socket@localhost",
        channel=None,
        message=message,
        config=config,
        client=client,
        logger=logger,
        roles=["owner"],
    )
    if not await commands.dispatch(context):
        await client.send_privmsg(
            "local", context.tr("Unknown command: {command}", command=line)
        )
    return True


class UnixControlServer:
    """A private local control endpoint; it never listens on TCP."""

    def __init__(
        self,
        socket_path: str | Path,
        commands: CommandRegistry,
        config: Config,
        logger: logging.Logger,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.commands = commands
        self.config = config
        self.logger = logger
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        if self._server:
            return
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists() or self.socket_path.is_symlink():
            mode = self.socket_path.lstat().st_mode
            if not stat.S_ISSOCK(mode):
                raise RuntimeError(
                    f"Control socket path exists and is not a socket: {self.socket_path}"
                )
            try:
                _reader, writer = await asyncio.open_unix_connection(
                    str(self.socket_path)
                )
            except (ConnectionRefusedError, FileNotFoundError):
                self.socket_path.unlink()
            except OSError as exc:
                raise RuntimeError(
                    f"Cannot inspect existing control socket: {self.socket_path}"
                ) from exc
            else:
                writer.close()
                await writer.wait_closed()
                raise RuntimeError(
                    f"Control socket is already in use: {self.socket_path}"
                )
        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(self.socket_path), limit=4096
        )
        os.chmod(self.socket_path, 0o600)
        self.logger.info("Local control socket listening at %s", self.socket_path)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.socket_path.exists() and stat.S_ISSOCK(self.socket_path.stat().st_mode):
            self.socket_path.unlink()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        async def output(message: str) -> None:
            writer.write(f"{message}\n".encode())
            await writer.drain()

        client = LocalCommandClient(output)
        try:
            await output("NovariusIRC local control. Type !help, !status, or exit.")
            while line := await reader.readline():
                try:
                    command = line.decode("utf-8").rstrip("\r\n")
                except UnicodeDecodeError:
                    await output("Invalid UTF-8 command")
                    continue
                if not await dispatch_local_command(
                    self.commands, self.config, self.logger, client, command
                ):
                    await output("Goodbye.")
                    break
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass


async def run_control_command(socket_path: str | Path, command: str) -> list[str]:
    """Send one command to the local endpoint and return its output lines."""
    reader, writer = await asyncio.open_unix_connection(str(socket_path), limit=4096)
    try:
        writer.write(f"{command}\nexit\n".encode())
        await writer.drain()
        lines = [line.decode("utf-8").rstrip("\r\n") async for line in reader]
        return [
            line
            for line in lines
            if line not in {"NovariusIRC local control. Type !help, !status, or exit.", "Goodbye."}
        ]
    finally:
        writer.close()
        await writer.wait_closed()
