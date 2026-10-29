# Feature inventory

**Languages:** [Deutsch](FEATURES.md) · English

This index reflects the current source tree. Optional features may be disabled
in a default instance. Configuration, protocol, plugin, and operations guides
describe their settings and limits.

## IRC protocol and connection

- One IRC network per process; multiple networks use separate instances.
- Async connection lifecycle with TLS, reconnect backoff, timeouts, graceful
  shutdown, bounded input, and rate-limited output.
- IRCv3 CAP 302, offered-capability checks, dynamic CAP NEW/DEL, tags, batches,
  server time, standard replies, and ISUPPORT-driven channel/user state.
- SASL PLAIN and EXTERNAL, TLS client certificates, NickServ identification,
  WHO/WHOX, and core CTCP PING/VERSION/CLIENTINFO handling.
- IRCv3 is optional for ordinary IRC operation. Optional server identity and
  presence data are handled as optional input.

See [IRC protocol support](IRC_PROTOCOL.md).

## Commands, identity, and access

- Shared case-insensitive command registry for core, built-in modules, and
  external plugins; duplicate command and alias registration is rejected.
- Query commands use the configured prefix. In channels, address the bot nick
  first; the prefix is optional after the address.
- Core commands: `help`, `ping`, `uptime`, `version`, `status`,
  and `botinfo`.
- User, admin, and owner roles support bindings by hostmask, IRCv3 account tag,
  or CertFP. Database-backed bindings use the owner-only `role` command.
- Optional test startup notices can be sent to explicitly configured nicks
  using `NOVARIUSIRC_TEST_HELLO_NICKS`; they contain no secrets.

## Configuration and localization

- Strict TOML, explicit includes, environment overrides, validation, and
  config status without connecting to IRC.
- English, German, and Japanese catalogs; language can be detected from the
  environment when not configured.
- Environment-only startup for container deployments.

See [configuration (DE)](CONFIGURATION.md) ·
[configuration (EN)](CONFIGURATION.en.md).

## Storage, backup, and monitoring

- SQLAlchemy Core backends: SQLite, PostgreSQL, MariaDB, MySQL, and Microsoft
  SQL Server. Server backends need a driver and DSN.
- Explicit database init/check/upgrade commands. SQLite uses WAL, full
  synchronous writes, foreign keys, and integrity checks.
- Persistent role and feed state. Moderation uses a separate SQLite database by
  default or dedicated tables on a configured SQL server.
- Verified offline SQLite/data backups with SHA-256 manifests, optional bzip3,
  listing, and explicit restore.
- Read-only Tornado monitoring API with health, readiness, and versioned
  status; psutil metrics are optional.
- Local CLI, terminal console, and Unix control socket; no TCP control port.

See [operations](OPERATIONS.md) and [configuration](CONFIGURATION.en.md).

## Built-in RSS/Atom module

- Optional `rss_announcer` with bounded polling, HTTP limits, TLS settings,
  and User-Agent options.
- ETag/Last-Modified support, persistent seen-item state, intervals,
  customizable templates, and bounded manual/automatic announcements.
- `feed` command for listing and refreshing feeds.

See [feed configuration](CONFIGURATION.en.md#feeds) and
[example](../config/feeds.example.toml).

## Core moderation

- Configurable rate, repeated-message, caps, word, and URL checks.
- Rules from config, reloadable files, and persistent database entries;
  per-channel overrides and runtime settings.
- Warning escalation, moderation actions, configurable target masks, decision
  logs, and persistent action/evidence metadata.
- Automated address/phone detection and RDAP/WHOIS lookup are not implemented.

See [moderation configuration](CONFIGURATION.en.md#moderation) and
[example](../config/moderation.example.toml).

## External plugin workers

- Explicitly allow-listed package plugins with metadata, dependencies,
  commands, and hook subscriptions.
- Optional child workers use bounded JSON IPC, limits, timeouts, core-side role
  checks, plugin-specific data directories, and termination on failure/unload.
- Workers are not a complete OS sandbox; they retain the bot user's filesystem
  and network permissions unless deployment isolation is added.

See [plugin guide](PLUGINS.md).

## Logging and build information

- Structured stdout; date-named rotating core logs; separate channel, private,
  raw-protocol, and moderation logs.
- Optional journald output and configurable destinations.
- `-v`, `-V`, and `--version` show build/runtime details;
  `botinfo` shows extended diagnostics over IRC.

See [operations](OPERATIONS.md) and [protocol guide](IRC_PROTOCOL.md).

## Deliberate limits

- No web panel, writable HTTP API, or public API authentication flow.
- Moderation depends on channel privileges and server-supported modes.
- Plugin workers provide process separation, not a complete security sandbox.
- Requesting a draft IRCv3 capability does not mean its higher-level semantics
  are implemented.

For operational status and remaining work, see
[startup readiness](STARTUP_READINESS.md).
