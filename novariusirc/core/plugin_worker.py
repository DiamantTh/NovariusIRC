"""Bounded JSON transport for opt-in, persistent plugin subprocesses."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path


class PluginWorker:
    def __init__(self, name, path, storage, settings, config):
        self.name = name
        self.path = path
        self.storage = storage
        self.settings = settings
        self.config = config
        self.process = None
        self.lock = asyncio.Lock()

    async def start(self):
        self.storage.mkdir(parents=True, exist_ok=True)
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, "-I", str(Path(__file__).with_name("plugin_worker_child.py")),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=self.storage,
            env={key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ") if key in os.environ},
            limit=self.config.worker_payload_bytes,
            start_new_session=os.name == "posix",
        )
        await self.request({
            "operation": "load", "path": str(self.path.resolve()),
            "settings": self.settings,
            "memory_mib": self.config.worker_memory_mebibytes,
            "limit": self.config.worker_payload_bytes,
        })

    async def request(self, payload):
        if self.lock.locked():
            raise RuntimeError("Plugin worker is busy")
        async with self.lock:
            try:
                async with asyncio.timeout(self.config.worker_timeout_seconds):
                    if self.process is None or self.process.returncode is not None:
                        raise RuntimeError("Plugin worker is stopped")
                    wire = json.dumps(payload, ensure_ascii=True).encode() + b"\n"
                    if len(wire) > self.config.worker_payload_bytes:
                        raise ValueError("Plugin request exceeds payload limit")
                    self.process.stdin.write(wire)
                    await self.process.stdin.drain()
                    raw = await self.process.stdout.readline()
                    if not raw or len(raw) > self.config.worker_payload_bytes:
                        raise ValueError("Invalid plugin response size")
                    response = json.loads(raw)
                    if not isinstance(response, dict) or response.get("ok") is not True:
                        raise RuntimeError("Plugin worker request failed")
                    replies = response.get("replies", [])
                    if not isinstance(replies, list) or len(replies) > 4:
                        raise ValueError("Invalid plugin replies")
                    for reply in replies:
                        if (not isinstance(reply, str) or len(reply.encode()) > 400
                                or any(char in reply for char in "\r\n\0\x01")):
                            raise ValueError("Invalid plugin reply")
                    return replies
            except BaseException:
                await self.on_unload()
                raise

    async def dispatch(self, ctx, command=None, args=None):
        replies = await self.request({
            "operation": "event", "event": ctx.event,
            "nick": ctx.nick, "channel": ctx.channel, "message": ctx.message,
            "language": ctx.language, "command": command, "args": args or [],
        })
        for reply in replies:
            await ctx.reply(reply)

    async def on_message(self, ctx):
        await self.dispatch(ctx)

    async def on_unload(self):
        process, self.process = self.process, None
        if process is not None:
            if process.returncode is None:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()
