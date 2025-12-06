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
3. Run the bot:
   ```bash
   poetry run novariusirc --config ./config.toml --profile default
   ```

## Project Layout
- `novariusirc/core`: core services (client, config, auth, commands, logging, i18n, feeds, plugins, workers)
- `novariusirc/modules`: built-in modules (moderation, rss_announcer)
- `novariusirc/__main__.py`: CLI entry point
- `config.example.toml`: starter configuration

## Notes
- Structured STDOUT logging plus rotating files under `logs/`; optional journald if installed.
- Secrets can be read from environment variables referenced in the config.
- Feed engine caches ETag/Last-Modified and tracks seen item ids per feed.
- Moderation module operates in warn-only mode for the MVP.
