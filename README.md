# NovariusIRC

NovariusIRC is a modular, multilingual IRC bot/daemon in the classic Eggdrop style. One process connects to exactly one IRC network; multi-network setups run multiple instances (or containers). The project targets Python 3.12+, ships a Poetry configuration, and exposes a CLI entry point `novariusirc`.

## Status
This repository contains the first MVP skeleton: async IRC core with reconnect logic, config loading and validation, structured logging, i18n hooks, a command registry with role checks, a feed engine, and sample modules for moderation (warn-only) and RSS announcements. Worker pools use `ProcessPoolExecutor` with an optional `aioprocessing` extra for long-lived workers.

## Quickstart
1. Install dependencies (optionally enable extras `uvloop`, `journald`, `workers`):
   ```bash
   poetry install
   ```
2. Copy `config.example.toml` to `config.toml` and adjust values or environment variables.
3. Optional features: create files next to `config.toml` named `feeds.toml`, `moderation.toml`, or `workers.toml` (samples in `config/*.example.toml`). They are loaded automatically if present.
4. Run the bot:
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
- Moderation module operates in warn-only mode for the MVP.
