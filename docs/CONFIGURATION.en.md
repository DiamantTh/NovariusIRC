# Configuration reference

**Languages:** [Deutsch](CONFIGURATION.md) · English

## Table of contents

- [Loading and validation](#loading)
- [Load order and includes](#includes)
- [Bot](#bot)
- [Network and IRCv3](#network)
- [Authentication](#auth)
- [Roles](#roles)
- [Owner bootstrap](#owner-bootstrap)
- [Logging](#logging)
- [Commands, lifecycle, and control](#commands-lifecycle-control)
- [Web API](#web-api)
- [Built-in modules](#modules)
- [Paths and workers](#paths-workers)
- [Database](#database)
- [Backups](#backups)
- [Feeds](#feeds)
  - [Feed definitions](#feed-definitions)
- [Moderation](#moderation)
  - [Checks and warnings](#moderation-checks)
- [External plugins](#plugins)
- [Environment variables](#environment)

NovariusIRC uses TOML. Key names remain English regardless of the bot's output
language so existing configurations, container variables, and tooling stay
compatible.

This page follows the practical structure of the
[InspIRCd configuration documentation](https://docs.inspircd.org/4/configuration/):
each section explains its purpose, parameters, defaults, and a short example.
It covers values currently evaluated by the core and built-in modules. The
complete starter configuration is
[`config.example.toml`](../config.example.toml).

<a id="loading"></a>
## Loading and validation

```console
novariusirc --check-config --config ./config.toml
novariusirc --status --config ./config.toml
novariusirc --config ./config.toml
```

`--check-config` does not connect to IRC. It validates the TOML structure,
required values, limits, referenced TLS files, writable runtime paths, and
importable built-in modules.

The `--config` argument accepts:

- a TOML file;
- a directory in which `config.toml` is located;
- `env`, `environment`, or `-` for an environment-only startup.

All typed sections reject unknown keys. A typo therefore fails startup instead
of being silently ignored. The free-form `plugins.settings` and
`moderation.channels` tables are intentional exceptions.

<a id="includes"></a>
## Load order and includes

The effective configuration is assembled in this order:

1. Load `config.toml`.
2. Recursively merge include files in their listed order. Later values override
   earlier values; lists are replaced in full.
3. Apply supported environment-variable overrides.
4. Validate cross-setting dependencies and resolve runtime paths.

Without an explicit include setting, an existing `secrets.toml` next to the
main file is loaded optionally. Once includes are configured explicitly, every
listed file must exist.

```toml
[includes]
files = ["secrets.toml", "feeds.toml", "moderation.toml"]
```

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `files` | list of text | `["secrets.toml"]` | Files to merge in load order; duplicate names are removed. |

The top-level shorthand is also supported:

```toml
include = ["secrets.toml", "feeds.toml"]
```

Include paths are relative to the main configuration directory. Absolute paths
are accepted as well. Credentials belong in an untracked file based on
[`secrets.example.toml`](../secrets.example.toml).

<a id="bot"></a>
## `[bot]`

General bot presentation and language.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | text | configured IRC nick | Stable instance name for data and backup files, independent of the runtime nick. |
| `prefix` | text | `!` | Command prefix in queries and local control. In channels, address the bot nick with `:` or `,`; the prefix after it is optional. |
| `language` | text | environment, then `en` | Output language: `de`, `en`, or `ja`. Locale forms such as `de_DE.UTF-8` are normalized. |
| `ctcp_version_extra` | text | empty | Optional suffix for CTCP `VERSION`; it cannot replace the product name or package version. Control characters and values exceeding 300 UTF-8 bytes are rejected. |

If `language` is omitted, the order is `NOVARIUSIRC_LANG`, `LANGUAGE`,
`LC_ALL`, `LC_MESSAGES`, `LANG`, then English.

```toml
[bot]
prefix = "!"
language = "en"
ctcp_version_extra = "Production instance"
```

<a id="network"></a>
## `[network]`

IRC connection, identity, and protocol limits. `server`, `nick`, `user`, and
`realname` are required in file-based configurations.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `server` | text | required | IRC server DNS name or IP address. |
| `port` | integer | `6667` | TCP port from 1 through 65535. Port 6697 is commonly used for TLS. |
| `tls` | Boolean | `false` | Enable an encrypted TLS connection. SASL and CertFP currently require TLS. |
| `bind_ip` | text or empty | empty | Local source IP for the outgoing connection. Takes precedence over `bind_hostname`. |
| `bind_hostname` | text or empty | empty | Local source hostname. |
| `nick` | text | required | Requested IRC nickname without whitespace or control characters. |
| `user` | text | required | Username for `USER`, without whitespace or control characters. |
| `realname` | text | required | Non-empty real name/GECOS text. |
| `channels` | list of text | `[]` | Channels to join after registration. |
| `name` | text or empty | from `005 NETWORK` | Manual internal network name. |
| `allow_unusual_channel_names` | Boolean | `false` | Allow characters other than Unicode letters, digits, `-`, and `_` after the channel prefix. |
| `reconnect_delays` | list of integers | `[10, 20, 40, 80]` | Positive delays in seconds for successive reconnect attempts. |
| `connect_timeout_seconds` | number | `30.0` | TCP/TLS connection timeout; must be greater than zero. |
| `registration_timeout_seconds` | number | `60.0` | Timeout for completing IRC registration. |
| `idle_timeout_seconds` | number | `300.0` | Maximum time without incoming IRC data before disconnecting. |
| `ircv3_enabled` | Boolean | `true` | Enable IRCv3 CAP negotiation. The bot remains compatible with older IRCds. |
| `ircv3_capabilities` | list of text | see example | Stable desired capabilities. Only capabilities offered by the server are requested. Do not add `sasl` here. |
| `ircv3_draft_capabilities` | list of text | `[]` | Explicit opt-ins whose names must start with `draft/`. |
| `send_rate_per_second` | number | `1.0` | Sustained outgoing IRC-line rate per second. |
| `send_burst` | integer | `4` | Short outgoing burst allowance, at least 1. |
| `send_queue_size` | integer | `256` | Maximum queued outgoing IRC lines. |
| `event_queue_size` | integer | `256` | Maximum queued application events. |

Standard channel prefixes are `#`, `&`, `+`, and `!`. Whitespace, commas,
colons, CR, LF, and NUL remain invalid in compatibility mode.

```toml
[network]
server = "irc.example.net"
port = 6697
tls = true
nick = "NovariusBot"
user = "novarius"
realname = "Novarius IRC Bot"
channels = ["#bots"]
```

<a id="auth"></a>
## `[auth]`

Authentication of the bot client to the IRC network. All methods are disabled
or ineffective until explicitly configured.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `sasl_enabled` | Boolean | `false` | Enable SASL during IRCv3 registration. |
| `sasl_mechanism` | text | `PLAIN` | Supported values are `PLAIN` and `EXTERNAL`. |
| `sasl_username` | text or empty | bot nick when enabled | SASL authentication name. |
| `sasl_password` | text or empty | empty | Password for SASL PLAIN. |
| `nickserv_enabled` | Boolean | `false` | Identify by sending a message to a services nick. |
| `nickserv_service` | text | `NickServ` | Services target name. |
| `nickserv_username` | text or empty | bot nick when enabled | NickServ account name. |
| `nickserv_password` | text or empty | empty | NickServ password. |
| `certfp_enabled` | Boolean | `false` | Load a TLS client certificate for the IRC connection. |
| `certfp_cert_file` | path or empty | empty | PEM certificate; required for SASL EXTERNAL. |
| `certfp_key_file` | path or empty | empty | Separate private key; leave empty if included in the PEM file. |

SASL PLAIN requires a username, password, and `network.tls = true`. SASL
EXTERNAL requires TLS, enabled CertFP, and a certificate file.

<a id="roles"></a>
## `[roles]`

Without an enabled database, the `owner` and `admin` roles continue to be
assigned through IRC hostmasks from this configuration. With a database,
`owners` is only a one-time owner seed on first startup and `admins` is no
longer used. An owner manages later assignments in the database with
`!role list`, `!role add`, and `!role remove`.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `owners` | list of roles | `[]` | Entries with full bot permissions. |
| `admins` | list of roles | `[]` | Entries with elevated but not full permissions. |

Each role entry supports:

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `hostmask` | text | required | `nick!user@host` pattern; `*` and `?` are wildcards. |

```toml
[roles]
owners = [
  { hostmask = "owner!*@trusted.example" },
]
admins = [
  { hostmask = "*!staff@*.example" },
]
```

Hostmasks also work on networks without NickServ or IRCv3. Privileged roles
should use stable server-assigned hosts; a nickname alone is not reliable proof
of identity.

<a id="owner-bootstrap"></a>
## `[owner_bootstrap]`

These values create owner bindings once during the first initialization of an
enabled database. The database then records that bootstrap is complete and
never uses them as a second authority source again—even if all owner bindings
are later removed. This is intended especially for the first container
installation.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `hostmask` | text or empty | empty | Hostmask pattern; works with classic IRCds too. |
| `account` | text or empty | empty | Exact IRC account name from the IRCv3 `account` tag. |
| `certfp` | text or empty | empty | Hex TLS certificate fingerprint from `certfp` or `solanum.chat/certfp`. Colons are accepted. |

```toml
[owner_bootstrap]
hostmask = "owner!*@trusted.example"
# account = "owner-account"
# certfp = "0123456789abcdef..."
```

For container-friendly first-time configuration,
`NOVARIUSIRC_OWNER_HOSTMASK`, `NOVARIUSIRC_OWNER_ACCOUNT`, and
`NOVARIUSIRC_OWNER_CERTFP` override the matching values. At least one owner
binding is required before database operation is startup-ready.

<a id="logging"></a>
## `[logging]`

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `level` | text | `INFO` | Python log level, converted to uppercase while loading. |
| `log_dir` | path | `logs` | Compatibility log path. A non-default value is used while `paths.log_root` remains `./logs`. |
| `timezone` | text | `Europe/Berlin` | IANA timezone for human-readable IRC logs. |
| `journald_enabled` | Boolean | `false` | Also send records to systemd-journald when the optional integration is available. |
| `channel_logging` | list of tables | `[]` | Explicit selection of channels whose messages are logged. |

Each channel entry requires `channel`; `enabled` defaults to `true`:

```toml
[[logging.channel_logging]]
channel = "#bots"
enabled = true
```

Message-level channel logging is disabled when no entry matches.

<a id="commands-lifecycle-control"></a>
## `[commands]`, `[lifecycle]`, and `[control]`

| Section.Name | Type | Default | Description |
| --- | --- | --- | --- |
| `commands.rate_limit_seconds` | number | `2.0` | Minimum interval for the same command by the same user; `0` disables the limit. |
| `lifecycle.module_start_timeout_seconds` | number | `30.0` | Timeout for starting a built-in module. |
| `lifecycle.module_stop_timeout_seconds` | number | `30.0` | Timeout for stopping a built-in module. |
| `control.enabled` | Boolean | `false` | Enable the local Unix control socket. |
| `control.socket_path` | path | `./run/novariusirc.sock` | Socket file created with mode `0600`. |

The control endpoint is neither a TCP listener nor a shell. It executes the
same registered bot commands as the terminal console.

<a id="web-api"></a>
## `[web_api]`

The future web API uses Tornado. It is disabled by default, so the current
version starts no HTTP listener regardless of these values. `host` and `port`
reserve its future operating address.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | Boolean | `false` | Prepares later API activation; currently has no listener effect. |
| `host` | text | `127.0.0.1` | Bind address. Use `0.0.0.0` only for a deliberately published container API. |
| `port` | integer | `9688` | TCP port of the future API. |

A Docker healthcheck needs no published Compose port mapping: it calls the
future listener on `127.0.0.1` inside the container.

<a id="modules"></a>
## `[modules]`

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | list of text | `["rss_announcer"]` | Built-in Python module names in startup order. Duplicates are removed. |

`rss_announcer` is the active built-in feature module. The old `moderation`
name exists only as a compatibility notice; moderation is already a core
service and should not be listed here. Unknown or unimportable modules make
`--check-config` fail.

<a id="paths-workers"></a>
## `[paths]` and `[workers]`

| Section.Name | Type | Default | Description |
| --- | --- | --- | --- |
| `paths.log_root` | path | `./logs` | Root directory for log files. |
| `paths.data_root` | path | `./data` | Root directory for persistent runtime data. Without a database, feed state is JSON here; with an enabled database it is stored in SQL. |
| `workers.processes` | integer | `2` | Process count for CPU-heavy work, at least 1. |

Relative runtime paths are resolved against the directory containing
`config.toml`, not the current working directory. This also applies to the
control socket, moderation log, certificates, and feed TLS files.

<a id="database"></a>
## `[database]`

The database layer is optional. SQLite is the first fully operational backend.
PostgreSQL, MariaDB, MySQL, and Microsoft SQL Server are already registered as
unambiguous backend names, but still require their adapters and are rejected
with an explicit error until those are available.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | Boolean | `false` | Enable the persistent database layer. |
| `backend` | choice | `sqlite` | `sqlite`, `postgresql`, `mariadb`, `mysql`, or `mssql`; aliases are normalized. |
| `path` | path or empty | `<data_root>/<bot.name>.sqlite3` | SQLite file. The bot name is normalized for safe filesystem use. |
| `dsn` | text or empty | empty | Connection DSN for server databases; preferably supplied through the environment. Invalid for SQLite. |
| `connect_timeout_seconds` | number | `10.0` | Connection timeout for server databases, greater than zero. |
| `busy_timeout_seconds` | number | `5.0` | SQLite lock wait time, at least zero. |

An enabled SQLite database must be created explicitly:

```console
novariusirc --init-database --config ./config.toml
novariusirc --check-database --config ./config.toml
```

Initialization enables foreign keys, WAL, `synchronous = FULL`, runs the
packaged Alembic migrations, and records the stable bot name. An unknown
existing SQLite file is not adopted. If an initialized database disappears,
the bot stops instead of silently creating an empty replacement. The earlier
SQLite metadata file is accepted during explicit initialization and moved to
the first Alembic revision.

<a id="backups"></a>
## `[backups]`

Backups are optional and deliberately started through the CLI only. SQLite is
read as a consistent snapshot through its backup API. The archive also includes
regular files below `paths.data_root`, but never the live database, its WAL/SHM
sidecars, or the backup directory itself. `manifest.json` records the SHA-256
hash and size of every included file.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | Boolean | `false` | Permit creating backups. |
| `directory` | path | `./backups` | Destination directory, relative to `config.toml`. |
| `compression` | choice | `none` | `none` keeps a portable `.tar`; `bzip3` compresses only above the threshold. |
| `compression_min_bytes` | integer | `8388608` | Minimum TAR size for optional bzip3 compression. `0` always compresses. |
| `include_data` | Boolean | `true` | Include regular extra files from `paths.data_root`. |

Names use only the stable bot name and UTC, for example
`MyBot_20260901T201530Z.tar`:

```console
novariusirc --backup-database --config ./config.toml
novariusirc --list-backups --config ./config.toml
```

For `compression = "bzip3"`, `bzip3` must be installed in the execution path.
Restoring is offline-only and explicitly requires `--replace-database`;
`--restore-data` also copies archived auxiliary files back:

```console
novariusirc --restore-database ./backups/MyBot_20260901T201530Z.tar \
  --replace-database --restore-data --config ./config.toml
```

<a id="feeds"></a>
## `[feeds]`

Global feed-core settings. The built-in `rss_announcer` module starts polling
when listed in `[modules].enabled`.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | Boolean | `true` | Enable feed processing globally. |
| `max_feeds` | integer | `32` | Maximum registered feeds. |
| `max_items_per_feed` | integer | `64` | Maximum remembered item IDs per feed. |
| `max_items_per_poll` | integer | `2` | Global maximum new announcements per automatic poll. |
| `max_items_per_manual` | integer | `4` | Global maximum per manually triggered poll. |
| `refresh_interval` | integer | `300` | Automatic polling interval in seconds. |
| `http_timeout` | integer | `10` | HTTP timeout in seconds. |
| `max_body_size` | integer | `262144` | Maximum response size in bytes, at least 1024. |
| `user_agents` | list of text | `[]` | Custom HTTP user agents. Empty uses `NovariusIRC/feeds`. |
| `user_agent_rotate` | choice | `list` | `list` rotates, `random` chooses randomly, and `fixed` uses the first entry. |
| `tls_allow_legacy` | Boolean | `false` | Enable the OpenSSL legacy-server-connect option. Use only for unavoidable legacy servers. |
| `tls_ca_file` | path or empty | empty | Custom CA bundle file. |
| `tls_ca_dir` | path or empty | empty | Custom CA certificate directory. |
| `tls_cert_file` | path or empty | empty | TLS client certificate for feed servers. |
| `tls_key_file` | path or empty | empty | Matching private key. |
| `feeds` | list of tables | `[]` | Individual feed definitions. |

Empty strings for the four TLS paths are treated as unset.

<a id="feed-definitions"></a>
### `[[feeds.feeds]]`

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | text | required | Display and internal name. |
| `url` | text | required | HTTP(S) URL of the RSS or Atom feed. |
| `channel` | text or empty | empty | Single target, also added to `channels`. |
| `channels` | list of text | `[]` | One or more targets. At least `channel` or `channels` is required. |
| `enabled` | Boolean | `true` | Enable or pause this feed. |
| `template` | text or empty | built in | Output template using `{feed}`, `{title}`, `{summary}`, `{link}`, and `{published}`. |
| `min_interval_seconds` | integer or empty | empty | Minimum announcement interval for this feed, at least 0. |
| `per_channel_interval` | table | `{}` | Per-target minimum intervals, e.g. `{ "#news" = 900 }`. |
| `max_items_per_poll` | integer or empty | global | Limit for each automatic poll. |
| `max_items_per_manual` | integer or empty | global | Limit for each manual poll. |

See [`config/feeds.example.toml`](../config/feeds.example.toml) for a complete
example including IRC formatting.

<a id="moderation"></a>
## `[moderation]`

Moderation is a core service. Individual checks are disabled by default, so
`moderation.enabled = true` alone performs no action. See
[`config/moderation.example.toml`](../config/moderation.example.toml) for the
complete example.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | Boolean | `true` | Allow core moderation globally. |
| `log_file` | path | `logs/moderation/moderation.log` | Dedicated rotating decision log. |
| `rate_limit` | table | see below | Message-rate limiting. |
| `spam` | table | see below | Repeated-message detection. |
| `caps` | table | see below | Excessive-uppercase detection. |
| `badwords` | table | see below | Regular-expression content filter. |
| `warnings` | table | see below | Warning escalation thresholds. |
| `channels` | table | `{}` | Recursive per-channel overrides. |

<a id="moderation-checks"></a>
### Checks and warnings

| Section.Name | Type | Default | Description |
| --- | --- | --- | --- |
| `rate_limit.enabled` | Boolean | `false` | Check message rate. |
| `rate_limit.messages_per_minute` | integer | `5` | Allowed messages per minute, at least 1. |
| `rate_limit.action` | choice | `warn` | Action when exceeded. |
| `spam.enabled` | Boolean | `false` | Detect immediately repeated identical messages. |
| `spam.threshold` | integer | `3` | Number of identical messages, at least 2. |
| `spam.action` | choice | `mute` | Action when detected. |
| `spam.duration_seconds` | integer | `300` | Mute duration in seconds. |
| `caps.enabled` | Boolean | `false` | Check uppercase percentage; messages with fewer than five letters are skipped. |
| `caps.threshold_percent` | integer | `80` | Threshold from 1 through 100 percent. |
| `caps.action` | choice | `warn` | Action when detected. |
| `badwords.enabled` | Boolean | `false` | Match regular expressions against message text. |
| `badwords.list` | list of text | `[]` | Case-insensitive Python regular expressions. |
| `badwords.action` | choice | `warn` | Action on a match. |
| `warnings.enabled` | Boolean | `true` | Escalate accumulated warnings automatically. |
| `warnings.to_kick` | integer | `3` | Kick at this warning count. |
| `warnings.to_ban` | integer | `5` | Ban at this warning count; cannot be less than `to_kick`. |

Valid actions are `warn`, `mute`, `kick`, and `ban`. `mute` uses quiet mode
`+q`; `ban` sets `+b` and then kicks. Support for `+q` and the privileges the
bot needs depend on the IRCd.

Channel values recursively override global values:

```toml
[moderation.channels."#strict".rate_limit]
enabled = true
messages_per_minute = 3
action = "mute"
```

<a id="plugins"></a>
## `[plugins]`

This section belongs to the core loader for external extensions. It is included
for completeness; built-in features belong under `[modules]`.

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | Boolean | `true` | Globally allow loading external extensions. |
| `directory` | path | `plugins` | Directory relative to `config.toml`. |
| `load` | list of text | `[]` | Explicit allowlist; names may contain letters, digits, `_`, and `-`. |
| `settings` | table | `{}` | Free-form extension settings grouped by name. |

<a id="environment"></a>
## Environment variables

These variables override supported TOML values. During file-based startup, the
four required `[network]` fields must still be present syntactically because
the base structure is validated before overrides are applied.

| Variable | Configuration value | Notes |
| --- | --- | --- |
| `NOVARIUSIRC_PREFIX` | `bot.prefix` | Non-empty text. |
| `NOVARIUSIRC_LANG` | `bot.language` | `de`, `en`, `ja`, or a matching locale form. |
| `NOVARIUSIRC_BOT_NAME` | `bot.name` | Stable name for data and backup files. |
| `NOVARIUSIRC_SERVER` | `network.server` | Required in environment-only mode. |
| `NOVARIUSIRC_PORT` | `network.port` | Only all-numeric values are applied. |
| `NOVARIUSIRC_TLS` | `network.tls` | True for `1`, `true`, `yes`, or `on`; false otherwise. |
| `NOVARIUSIRC_NICK` | `network.nick` | Required in environment-only mode. |
| `NOVARIUSIRC_USER` | `network.user` | Defaults to the nick in environment-only mode. |
| `NOVARIUSIRC_REALNAME` | `network.realname` | Defaults to the nick in environment-only mode. |
| `NOVARIUSIRC_CHANNELS` | `network.channels` | Comma-separated list. |
| `NOVARIUSIRC_BIND_IP` | `network.bind_ip` | Local source IP. |
| `NOVARIUSIRC_BIND_HOSTNAME` | `network.bind_hostname` | Local source hostname. |
| `NOVARIUSIRC_SASL_ENABLED` | `auth.sasl_enabled` | Boolean syntax as for TLS. |
| `NOVARIUSIRC_SASL_MECHANISM` | `auth.sasl_mechanism` | `PLAIN` or `EXTERNAL`. |
| `NOVARIUSIRC_SASL_USERNAME` | `auth.sasl_username` | SASL account name. |
| `NOVARIUSIRC_SASL_PASSWORD` | `auth.sasl_password` | Secret value. |
| `NOVARIUSIRC_NICKSERV_ENABLED` | `auth.nickserv_enabled` | Boolean syntax as for TLS. |
| `NOVARIUSIRC_NICKSERV_SERVICE` | `auth.nickserv_service` | Services target name. |
| `NOVARIUSIRC_NICKSERV_USERNAME` | `auth.nickserv_username` | Services account name. |
| `NOVARIUSIRC_NICKSERV_PASSWORD` | `auth.nickserv_password` | Secret value. |
| `NOVARIUSIRC_CERTFP_ENABLED` | `auth.certfp_enabled` | Boolean syntax as for TLS. |
| `NOVARIUSIRC_CERTFP_CERT_FILE` | `auth.certfp_cert_file` | Certificate path. |
| `NOVARIUSIRC_CERTFP_KEY_FILE` | `auth.certfp_key_file` | Private-key path. |
| `NOVARIUSIRC_LOG_ROOT` | `paths.log_root` | Log root directory. |
| `NOVARIUSIRC_DATA_ROOT` | `paths.data_root` | Data root directory. |
| `NOVARIUSIRC_DATABASE_ENABLED` | `database.enabled` | Boolean syntax as for TLS. |
| `NOVARIUSIRC_DATABASE_BACKEND` | `database.backend` | Registered backend name or alias. |
| `NOVARIUSIRC_DATABASE_PATH` | `database.path` | SQLite file path. |
| `NOVARIUSIRC_DATABASE_DSN` | `database.dsn` | Server-database connection DSN; secret value. |
| `NOVARIUSIRC_WEB_API_ENABLED` | `web_api.enabled` | Boolean syntax as for TLS. |
| `NOVARIUSIRC_WEB_API_HOST` | `web_api.host` | Bind address of the future API. |
| `NOVARIUSIRC_WEB_API_PORT` | `web_api.port` | TCP port between 1 and 65535. |
| `NOVARIUSIRC_OWNER_HOSTMASK` | `owner_bootstrap.hostmask` | One-time owner hostmask. |
| `NOVARIUSIRC_OWNER_ACCOUNT` | `owner_bootstrap.account` | One-time owner IRC account name. |
| `NOVARIUSIRC_OWNER_CERTFP` | `owner_bootstrap.certfp` | One-time owner CertFP. |

Environment-only startup requires at least `NOVARIUSIRC_SERVER` and
`NOVARIUSIRC_NICK`:

```console
NOVARIUSIRC_SERVER=irc.example.net \
NOVARIUSIRC_NICK=NovariusBot \
NOVARIUSIRC_TLS=true \
novariusirc --config env
```
