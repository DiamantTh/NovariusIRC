# Feature inventory

**Languages:** Deutsch · [English](FEATURES.en.md)

This index reflects the implementation in the current source tree. It is an
inventory of working code, not a promise that every optional feature is enabled
in a default instance. The configuration reference documents feature switches
and settings; the protocol, plugin, and operations guides describe behavior and
limits.

## IRC protocol and connection

- One IRC network per process; run separate instances for multiple networks.
- Async connection lifecycle with TLS, reconnect backoff, timeouts, graceful
  shutdown, bounded incoming lines, and rate-limited outgoing messages.
- IRCv3 CAP 302 negotiation, offered-capability checks, dynamic CAP NEW/DEL,
  message tags, batches, server time, and structured standard replies.
- SASL PLAIN and EXTERNAL, plus TLS client certificates and NickServ
  identification.
- ISUPPORT-driven casemapping, channel/user state, membership prefixes,
  channel modes, WHO/WHOX, and channel length limits.
- IRCv3 is optional for ordinary IRC operation; account tags, away state, and
  other extensions remain optional when a server does not provide them.
- CTCP PING, VERSION, and CLIENTINFO; VERSION reports the package identity.

Details: [IRC protocol support](IRC_PROTOCOL.md).

## Bot commands, identity, and access

- Shared case-insensitive command registry for core, built-in modules, and
  external plugins; duplicate names and aliases are rejected.
- Query commands use the configured prefix. In channels, address the bot nick
  first; the prefix is optional after that address.
- Built-in commands include `help`, `ping`, `uptime`, `version`,
  `status`, and `botinfo`.
- Role checks support user, admin, and owner levels. Identities can be bound by
  hostmask, IRCv3 account tag, or CertFP; database-backed bindings are managed
  with the owner-only `role` command.
- Startup test notices are opt-in through `NOVARIUSIRC_TEST_HELLO_NICKS` and
  report non-secret connection/configuration facts to explicitly listed nicks.

## Configuration and localization

- Strict TOML configuration, explicit relative/absolute includes, supported
  environment overrides, config validation, and config status without an IRC
  connection.
- English, German, and Japanese language catalogs with environment-based
  language detection when no language is configured.
- Environment-only startup is available for container-oriented deployments.

Details: [configuration reference (DE)](CONFIGURATION.md) ·
[configuration reference (EN)](CONFIGURATION.en.md).

## Persistent data, backups, and monitoring

- SQLAlchemy Core storage for SQLite, PostgreSQL, MariaDB, MySQL, and Microsoft
  SQL Server backends. Server backends require their database driver and
  configured DSN.
- Explicit database init/check/upgrade commands; SQLite uses WAL, full
  synchronous writes, foreign keys, and integrity checks.
- Persistent role bindings and feed state; moderation state uses a separate
  SQLite database by default and dedicated tables on configured SQL backends.
- Verified offline SQLite/data backups with SHA-256 manifests, optional bzip3
  compression, listing, and explicit restore.
- Read-only Tornado monitoring API with health/readiness and versioned status
  data; optional psutil metrics. No write API or web panel.
- CLI, terminal console, and local Unix control socket; the socket uses local
  filesystem permissions and does not open a TCP control port.

Details: [operations](OPERATIONS.md) ·
[database and API configuration](CONFIGURATION.md).

## Built-in module: RSS/Atom

- Optional `rss_announcer` module with bounded polling and HTTP response size,
  timeout, TLS, and User-Agent settings.
- ETag/Last-Modified handling, persistent seen-item state, per-feed and
  per-channel intervals, templates, and manual/automatic item limits.
- `feed` command for listing feeds and requesting bounded manual refreshes.

Details: [feed configuration](CONFIGURATION.md#feeds) ·
[example](../config/feeds.example.toml).

## Core moderation

- Core service with rate-limit, repeated-message, caps, word-rule, and URL-rule
  checks; each check is independently configurable.
- Allow/block patterns can come from config, reloadable rule files, and
  persistent database rules. Runtime settings can be overridden per channel.
- Warning escalation and kick/ban/mute handling, configurable target masks,
  decision logs, and persistent action/evidence metadata.
- No automated address/phone detection or RDAP/WHOIS lookup is currently
  listed as implemented.

Details: [moderation configuration](CONFIGURATION.md#moderation) ·
[example](../config/moderation.example.toml).

## External plugin workers

- External plugins are explicitly allow-listed. Package plugins declare
  metadata, dependencies, commands, and hook subscriptions.
- Optional child-process workers use bounded JSON IPC, payload/reply limits,
  timeouts, role checks in the core, plugin-specific data directories, and
  process termination on failure or unload.
- A child process is not an operating-system sandbox: it still has the bot
  user's filesystem and network permissions unless the deployment adds its own
  isolation.

Details: [plugin guide](PLUGINS.md).

## Logging and build information

- Structured stdout and rotating, date-named core logs; channel, private-message,
  raw-protocol, and moderation logs are separate configurable streams.
- Optional journald output; log retention and destinations are configurable.
- `-v`, `-V`, and `--version` report package/build/runtime details;
  `botinfo` is the IRC command for extended diagnostics.

See [operations](OPERATIONS.md) and [build information](IRC_PROTOCOL.md).

## Deliberate limits

- No web control panel, writable HTTP API, or public API authentication flow.
- IRC moderation depends on channel privileges and server-supported modes.
- Plugin workers provide process separation, not a complete security sandbox.
- Draft IRCv3 capabilities can be requested explicitly, but doing so does not
  imply that higher-level draft semantics are implemented.

For operational readiness and remaining work, see
[startup readiness](STARTUP_READINESS.md).
