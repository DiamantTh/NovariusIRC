# External plugins

External plugins are local Python extensions stored in `plugins/`. Merely
placing a file there does not execute it. As with Eggdrop scripts, the operator
must explicitly name every plugin in the instance configuration:

```toml
[plugins]
enabled = true
directory = "plugins"
load = ["example_greetings"]
```

The name `example_greetings` resolves to either
`plugins/example_greetings.py` or `plugins/example_greetings/__init__.py`.
Paths, dotted imports, and parent-directory references are rejected. A module
must define exactly one subclass of `BasePlugin`.

## Commands

External and built-in commands use the same `CommandRegistry`. Consequently,
aliases, role checks, rate limiting, error handling, and `!help` work in one
place rather than through a second plugin-only dispatcher.

```python
from novariusirc.core.plugins import BasePlugin, CommandContext, command


class SearchPlugin(BasePlugin):
    name = "search"

    @command(role="user", aliases=("find",), help_text="Search public records")
    async def cmd_search(self, ctx: CommandContext, args: list[str]) -> None:
        query = " ".join(args).strip()
        if not query:
            await ctx.reply("Usage: !search <query>")
            return
        await ctx.reply(f"Searching for: {query}")
```

Handlers receive a `CommandContext` and the parsed argument list. Use
`await ctx.reply(text)` to answer in the originating channel or private
conversation. Supported roles are `user`, `admin`, and `owner`; higher roles
inherit lower-role commands. Command and alias collisions make plugin loading
fail visibly.

## Lifecycle and hooks

`on_load()` runs after core services and commands have been bound. `on_unload()`
runs during clean shutdown. Plugins may override `on_message`, `on_join`,
`on_part`, `on_quit`, and `on_nick_change`; each receives a `CommandContext`.
When a plugin unloads, all of its commands, aliases, and hooks are removed.

Settings are available through `self.config.plugins.settings`; each plugin
should document the key it reads. Network access and background tasks belong in
the plugin and must be stopped in `on_unload()`.

## Trust boundary

A plugin is executable Python code with the same operating-system permissions
as the bot. The allow-list prevents accidental loading; it is not a sandbox.
Only install and enable code you trust, and keep API credentials in included
secret configuration or environment variables rather than in the plugin file.
