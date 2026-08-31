# NovariusIRC

NovariusIRC is a modular, multilingual IRC bot/daemon in the classic Eggdrop style. One process connects to exactly one IRC network; multi-network setups run multiple instances (or containers). The project targets Python 3.12+, ships a Poetry configuration, and exposes a CLI entry point `novariusirc`.

## Status
This repository contains the first MVP skeleton: async IRC core with reconnect logic, config loading and validation, structured logging, i18n hooks, a shared command registry with role checks, a feed engine, core moderation, and RSS announcements. CPU-heavy jobs can use the standard-library `ProcessPoolExecutor` worker pool.

## Quickstart
1. Recommended installation path:
   ```bash
   make install
   ```
2. Copy `config.example.toml` to `config.toml` and adjust values or environment variables.
3. Optional feature files are configured explicitly via `[includes]` in `config.toml`; entries are relative to `config.toml` (or absolute). Templates are in `config/*.example.toml`. `workers` stays in the main config by default.
4. Add the installed binary location to your shell `PATH`:
   ```bash
   export PATH="$HOME/NovariusIRC/bin:$PATH"
   ```
5. Run the example instance:
   ```bash
   novariusirc ~/NovariusIRC/instances/example/config.toml
   ```

### Development workflow (optional)
For local development in the project workspace, use Poetry:

```bash
poetry install
```

Then run the bot:

```bash
poetry run novariusirc --config ./config.toml
```

Validate an instance before connecting it to IRC. This loads and validates the
configuration, referenced TLS files, and enabled built-in modules, but does not
create log directories, start feeds, or open a network connection:

```bash
poetry run novariusirc --check-config --config ./config.toml
```

The optional database layer currently provides the complete SQLite lifecycle.
After enabling `[database]`, initialize it explicitly; normal startup never
silently recreates a missing database:

```bash
poetry run novariusirc --init-database --config ./config.toml
poetry run novariusirc --check-database --config ./config.toml
```

Show the configured instance status without opening an IRC connection:

```bash
poetry run novariusirc --status --config ./config.toml
```

For local operator control, `-t` starts the bot together with an interactive
terminal console. It executes registered bot commands as the local owner and
does not open a TCP listener or use DCC:

```bash
poetry run novariusirc -t --config ./config.toml
```

Use `!help`, `!status`, or `exit` in the console.

For non-interactive local operations, enable the Unix socket in `[control]`.
It is created with `0600` permissions and runs the same registered commands as
the terminal console; it is neither a TCP service nor an operating-system
shell. With the bot running, send one command through it:

```bash
poetry run novariusirc --ctl "!status" --config ./config.toml
```

## Container
Build a local image:
```bash
docker build -t novariusirc:local .
```

Embed the source revision as immutable build information (the UTC build time is
generated inside the build):

```bash
docker build \
  --build-arg NOVARIUSIRC_BUILD_COMMIT="$(git rev-parse HEAD)" \
  -t novariusirc:local .
```

For reproducible builds, `SOURCE_DATE_EPOCH` can additionally be supplied as a
build argument. `novariusirc -v`, `-V`, and `--version` show the same detailed
local build and runtime report. IRC `version` and CTCP `VERSION` remain compact;
the explicit IRC `botinfo` command shows the extended build and feature report.

Run the container. Mount the complete instance directory so relative includes,
certificates, and external plugins stay available; keep data and logs writable:
```bash
docker run --rm \
  -v "$(pwd)/instance:/app/instance:ro" \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  -e NOVARIUSIRC_DATA_ROOT=/app/data \
  -e NOVARIUSIRC_LOG_ROOT=/app/logs \
  novariusirc:local --config /app/instance/config.toml
```

Podman with SELinux label:
```bash
podman run --rm \
  -v "$(pwd)/instance:/app/instance:ro,Z" \
  -v "$(pwd)/data:/app/data:Z" \
  -v "$(pwd)/logs:/app/logs:Z" \
  -e NOVARIUSIRC_DATA_ROOT=/app/data \
  -e NOVARIUSIRC_LOG_ROOT=/app/logs \
  novariusirc:local --config /app/instance/config.toml
```

For an environment-only container, pass `--config env` and at minimum set
`NOVARIUSIRC_SERVER` and `NOVARIUSIRC_NICK`. The image handles `SIGINT` and
`SIGTERM` for a graceful stop and runs as an unprivileged user.

## Project Layout
- `novariusirc/irc`: protocol-focused IRC transport, capability and state primitives; independent of bot commands and modules
- `novariusirc/core`: bot services (client adapter, config, local control, auth, commands, logging, i18n, feeds, plugins, workers)
- `novariusirc/core/database.py`: database backend registry and SQLite lifecycle
- `novariusirc/modules`: built-in modules (currently `rss_announcer`)
- `novariusirc/__main__.py`: CLI entry point
- `config.example.toml`: starter configuration
- `config/*.example.toml`: optional feature snippets (feeds, moderation, workers)
- `docs/CONFIGURATION.md` / `docs/CONFIGURATION.en.md`: complete German and English configuration reference
- `LICENSE`: GNU AGPLv3 license text
- `VALUES.md`: non-binding project values and public-code position
- `docs/LICENSING.md`: license history and reason for the change
- `docs/PLUGINS.md`: external plugin loading, lifecycle, commands, and safety

## Notes
- Structured STDOUT logging plus rotating files under `logs/`; optional journald if installed.
- Core and built-in module replies use gettext catalogs for `de`, `en`, and
  `ja`. If `[bot].language` is omitted, startup checks `NOVARIUSIRC_LANG`,
  `LANGUAGE`, `LC_ALL`, `LC_MESSAGES`, and `LANG`, then falls back to English.
- The connection core supports IRCv3 CAP 302, message tags, SASL PLAIN and
  EXTERNAL, dynamic `CAP NEW`/`DEL`, server time, identity/presence events,
  WHO/WHOX snapshots, and the relevant `RPL_ISUPPORT` network features.
  Incoming protocol work is separated from a bounded, ordered application
  event queue, so a slow command or plugin cannot delay `PING`/`PONG`.
  See [docs/IRC_PROTOCOL.md](docs/IRC_PROTOCOL.md) for the exact support matrix.
- IRC connection settings and secrets can be overridden via env vars (e.g. `NOVARIUSIRC_SERVER`, `NOVARIUSIRC_NICK`, `NOVARIUSIRC_SASL_PASSWORD`).
- All supported TOML sections, parameters, defaults, limits, includes, and
  environment overrides are documented in
  [Deutsch](docs/CONFIGURATION.md) and
  [English](docs/CONFIGURATION.en.md).
- Env-only startup is supported; set `NOVARIUSIRC_SERVER` and `NOVARIUSIRC_NICK` (others optional) or pass `--config env`.
- Feed engine caches ETag/Last-Modified, tracks seen item ids per feed, supports custom templates (`{feed}`, `{title}`, `{summary}`, `{link}`, `{published}`), per-feed enable/disable, and User-Agent rotation/TLS settings (see `config/feeds.example.toml`).
- Feed overview command is available when `rss_announcer` is enabled: `!feed list [query]` (shows channels and active limits/options).
- Core status is available through `!status` and reports connection, network,
  active built-in modules, and feed-engine state.
- In a private query, `!version` returns the compact public version and
  `!botinfo` adds the current nick, network, connection state, uptime, build,
  runtime, features, and optional-component information. In channels, address
  the bot nick as described below.
- Built-in modules are configurable via `[modules].enabled` (e.g. `rss_announcer`).
- External plugins live in `plugins/`, but are loaded only when named in `[plugins].load`. Their commands use the same aliases, role checks, help listing, and rate limiting as built-in commands.
- Channel commands require the bot's current nick, for example
  `NovariusIRC: help` or `NovariusIRC, status`; using its configured prefix
  remains optional after the nick. This prevents several bots with overlapping
  command names or prefixes from answering together. In a private query and on
  local Terminal/Control interfaces, normal commands such as `!help` work
  without a bot nick.
- Moderation is a core service configured through `[moderation]`; it must not also be loaded as a module.

## License

NovariusIRC is licensed under the GNU Affero General Public License, version 3
or any later version (`AGPL-3.0-or-later`). See [LICENSE](LICENSE), the
non-binding [project values](VALUES.md), and the [licensing history](docs/LICENSING.md).
