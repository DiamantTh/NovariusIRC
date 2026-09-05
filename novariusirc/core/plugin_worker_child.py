"""Private worker entry point; plugin code is imported only in this process."""

import asyncio
import importlib.util
import inspect
import json
import sys
from pathlib import Path


async def main():
    reader, writer = sys.stdin.buffer, sys.stdout.buffer
    # Plugin print() output cannot corrupt the protocol.
    sys.stdout = sys.stderr
    limit = 65536
    handler = None
    while True:
        raw = reader.readline(limit + 1)
        if not raw or len(raw) > limit:
            return
        try:
            event = json.loads(raw)
            if event["operation"] == "load" and handler is None:
                limit = event["limit"]
                if event["memory_mib"] is not None:
                    import resource

                    ceiling = event["memory_mib"] * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))
                spec = importlib.util.spec_from_file_location(
                    "novarius_worker_plugin", event["path"],
                    submodule_search_locations=[str(Path(event["path"]).parent)],
                )
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                handler = module.handle
                settings = event["settings"]
                replies = []
            elif event["operation"] == "event" and handler is not None:
                replies = handler(event, settings)
                if inspect.isawaitable(replies):
                    replies = await replies
            else:
                raise ValueError("Invalid operation")
            response = json.dumps({"ok": True, "replies": replies}).encode() + b"\n"
            if len(response) > limit:
                return
            writer.write(response)
            writer.flush()
        except Exception:  # noqa: BLE001 -- report plugin failure without leaking its exception
            writer.write(b'{"ok":false}\n')
            writer.flush()
            return


if __name__ == "__main__":
    asyncio.run(main())
