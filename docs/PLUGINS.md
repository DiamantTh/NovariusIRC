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

New plugins should use the package form and include `novarius_plugin.toml`:

```text
plugins/weather/
  novarius_plugin.toml
  __init__.py
  commands.py
```

The manifest is read before importing package code and its `[plugin].name`
must equal the configured name. Single-file plugins remain compatibility-only.

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
runs during clean shutdown. Every hook receives one `CommandContext`:

| Hook | `ctx.event` | Additional `ctx.metadata` |
| --- | --- | --- |
| `on_message` | `PRIVMSG` | — |
| `on_action` | `ACTION` | — |
| `on_notice` | `NOTICE` | — |
| `on_join` | `JOIN` | `realname` |
| `on_part` | `PART` | — |
| `on_quit` | `QUIT` | `channels` |
| `on_nick_change` | `NICK` | `old_nick`, `new_nick`, `channels` |
| `on_kick` | `KICK` | `target` |
| `on_mode` | `MODE` | `arguments` |
| `on_topic` | `TOPIC` | — |
| `on_account` | `ACCOUNT` | — |
| `on_away` | `AWAY` | `away` |
| `on_chghost` | `CHGHOST` | `old_hostmask` |
| `on_invite` | `INVITE` | `target` |
| `on_tagmsg` | `TAGMSG` | `target` |

The common fields are `ctx.nick`, `ctx.hostmask`, `ctx.channel`, `ctx.message`,
`ctx.account`, `ctx.tags`, `ctx.server_time`, and `ctx.roles`. `ctx.channel` is
`None` for private messages and events without one. IRCv3 server time is an
aware UTC `datetime` when the server supplied a valid `time` tag.

Hooks and commands run in arrival order on a bounded application queue. This
keeps the IRC protocol reader responsive, but one slow handler still delays the
following application events. Use explicit network timeouts. If the queue
reaches `[network].event_queue_size`, new application events are dropped with a
warning instead of consuming unbounded memory. When a plugin unloads, all of
its commands, aliases, and hooks are removed.

Settings are available through `self.config.plugins.settings`; each plugin
should document the key it reads. Network access and background tasks belong in
the plugin and must be stopped in `on_unload()`.

## Trust boundary

A plugin is executable Python code with the same operating-system permissions
as the bot. The allow-list prevents accidental loading; it is not a sandbox.
Only install and enable code you trust, and keep API credentials in included
secret configuration or environment variables rather than in the plugin file.

## Current model and deliberate limits

Novarius plugins are Python extensions, not a Python spelling of Eggdrop Tcl.
They use the shared command registry and receive structured IRC events, but
they do **not** receive an unrestricted second bot framework. Before porting a
script, check whether its task belongs in the core, a built-in module, or an
external plugin.

The current in-process model has these limits:

- Plugin code runs in the bot process under the bot's Unix user. The allow-list
  is an activation safeguard, not a security sandbox.
- Hooks are ordered. A slow hook delays later application events, even though
  it cannot block IRC `PING`/`PONG`; use timeouts and short work units.
- A plugin must not modify the bot configuration, migrations, role bindings,
  control socket, or another plugin's state.
- A plugin must not assume IRCv3. Account tags, server time, and several hooks
  are absent on older networks and must be treated as optional input.
- Plugin exceptions during a hook are logged; load failures abort startup of
  the configured plugin set rather than silently leaving a partial set active.

## Storage and files

Separate executable plugin code from mutable plugin data. A recommended
instance layout is:

```text
plugins/
  code/
    weather.py
  data/
    weather/
      cache.json
```

The current `plugins.directory` is the code directory. Mutable state should
use a plugin-specific directory below the instance data root, for example
`data/plugins/weather/`; it must never be written beside code merely because
the code directory is convenient. Small structured state can later use the
shared SQL storage under a plugin-specific namespace. Large caches, downloads,
or evidence remain files with metadata in SQL where appropriate.

The core does not yet expose a stable plugin-storage API. Until it does, a
plugin's storage format is private to that plugin and must be documented by
the plugin author.

## Planned worker model

The intended hardening direction is a plugin worker process with local IPC:

```text
IRC core  <->  authenticated local IPC  <->  plugin worker  <->  plugin data
```

The core retains IRC connectivity, roles, database migrations, control, and
policy decisions. A worker receives only permitted events and can request a
limited reply or its own storage operation. A crash, timeout, or restart then
affects that plugin rather than the IRC connection.

A separate Python process alone is fault isolation, not a security sandbox.
Meaningful isolation additionally requires a separate Unix UID where practical,
only the plugin's data directory mounted writable, read-only code, no Docker
socket, and a narrowly defined IPC capability set. This worker protocol and
capability manifest are future work; external plugins therefore remain an
advanced, trusted-operator feature for this release.
