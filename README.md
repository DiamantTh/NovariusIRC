# NovariusIRC

NovariusIRC is a modular, multilingual IRC bot/daemon in the classic Eggdrop style. One process connects to exactly one IRC network; multi-network setups run multiple instances (or containers). The project targets Python 3.12+, ships a Poetry configuration, and exposes a CLI entry point `novariusirc`.

## Status
This repository contains the first MVP skeleton: async IRC core with reconnect logic, config loading and validation, structured logging, i18n hooks, a command registry with role checks, a feed engine, and sample modules for moderation (warn-only) and RSS announcements. Worker pools use `ProcessPoolExecutor` with an optional `aioprocessing` extra for long-lived workers.

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
- `novariusirc/modules`: built-in modules (moderation, rss_announcer)
- `novariusirc/__main__.py`: CLI entry point
- `config.example.toml`: starter configuration
- `config/*.example.toml`: optional feature snippets (feeds, moderation, workers)
- `licenses/Novara-Software-Freedom-License-EN.md`: project license text

## Notes
- Structured STDOUT logging plus rotating files under `logs/`; optional journald if installed.
- IRC connection settings and secrets can be overridden via env vars (e.g. `NOVARIUSIRC_SERVER`, `NOVARIUSIRC_NICK`, `NOVARIUSIRC_SASL_PASSWORD`).
- Env-only startup is supported; set `NOVARIUSIRC_SERVER` and `NOVARIUSIRC_NICK` (others optional) or pass `--config env`.
- Feed engine caches ETag/Last-Modified, tracks seen item ids per feed, supports custom templates (`{feed}`, `{title}`, `{summary}`, `{link}`, `{published}`), per-feed enable/disable, and User-Agent rotation/TLS settings (see `config/feeds.example.toml`).
- Feed overview command is available when `rss_announcer` is enabled: `!feed list [query]` (shows channels and active limits/options).
- Built-in modules are configurable via `[modules].enabled` (e.g. `moderation`, `rss_announcer`).
- Multi-bot IRC environments should use different prefixes per bot (recommended) to avoid command collisions.
- Moderation module operates in warn-only mode for the MVP.
