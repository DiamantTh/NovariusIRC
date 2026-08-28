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

## Container
Build a local image:
```bash
docker build -t novariusirc:local .
```

Run the container (mount your config):
```bash
docker run --rm -v "$(pwd)/config.toml:/app/config.toml:ro" novariusirc:local
```

Podman with SELinux label:
```bash
podman run --rm -v "$(pwd)/config.toml:/app/config.toml:ro,Z" novariusirc:local
```

## Project Layout
- `novariusirc/core`: core services (client, config, auth, commands, logging, i18n, feeds, plugins, workers)
- `novariusirc/modules`: built-in modules (currently `rss_announcer`)
- `novariusirc/__main__.py`: CLI entry point
- `config.example.toml`: starter configuration
- `config/*.example.toml`: optional feature snippets (feeds, moderation, workers)
- `LICENSE`: GNU AGPLv3 license text
- `VALUES.md`: non-binding project values and public-code position
- `docs/LICENSING.md`: license history and reason for the change
- `docs/PLUGINS.md`: external plugin loading, lifecycle, commands, and safety

## Notes
- Structured STDOUT logging plus rotating files under `logs/`; optional journald if installed.
- IRC connection settings and secrets can be overridden via env vars (e.g. `NOVARIUSIRC_SERVER`, `NOVARIUSIRC_NICK`, `NOVARIUSIRC_SASL_PASSWORD`).
- Env-only startup is supported; set `NOVARIUSIRC_SERVER` and `NOVARIUSIRC_NICK` (others optional) or pass `--config env`.
- Feed engine caches ETag/Last-Modified, tracks seen item ids per feed, supports custom templates (`{feed}`, `{title}`, `{summary}`, `{link}`, `{published}`), per-feed enable/disable, and User-Agent rotation/TLS settings (see `config/feeds.example.toml`).
- Feed overview command is available when `rss_announcer` is enabled: `!feed list [query]` (shows channels and active limits/options).
- Built-in modules are configurable via `[modules].enabled` (e.g. `rss_announcer`).
- External plugins live in `plugins/`, but are loaded only when named in `[plugins].load`. Their commands use the same aliases, role checks, help listing, and rate limiting as built-in commands.
- Multi-bot IRC environments should use different prefixes per bot (recommended) to avoid command collisions.
- Moderation is a core service configured through `[moderation]`; it must not also be loaded as a module.

## License

NovariusIRC is licensed under the GNU Affero General Public License, version 3
or any later version (`AGPL-3.0-or-later`). See [LICENSE](LICENSE), the
non-binding [project values](VALUES.md), and the [licensing history](docs/LICENSING.md).
