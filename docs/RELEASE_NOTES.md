# Release notes

## Unreleased 0.1.5

This is the first operational Core/modules release candidate. It is intended
for one bot instance per IRC network; external plugins and a public web
interface are not part of this release scope.

### Included

- Async IRC core with TLS, reconnects, optional IRCv3, SASL, bounded outbound
  flow control, and isolated application event processing.
- TOML/ENV configuration, instance layout, native installer, container image,
  build metadata, and German/English/Japanese bot output.
- Persistent roles and feed state using SQLite, Alembic migrations, verified
  SQLite backups, and explicit offline restore.
- Local Unix control socket, Typer CLI command groups, and a read-only local
  monitoring API (`/_health`, `/_ready`, `/v1/status`).

### Compatibility and operation

- Python 3.12 through 3.14 are supported by the project metadata.
- SQLite is the supported database backend. Server database backend names are
  reserved but not yet a supported production option.
- IRCv3 is optional. Hostmask-based owner bindings remain available for older
  IRC networks.
- The earlier single CLI flags remain accepted as compatibility aliases; new
  documentation uses `config`, `database`, `ctl`, and `console` commands.

### Not included

- Public API authentication, web panel, OpenAPI/Swagger, or OAuth/OIDC.
- External-plugin sandboxing or a stable external-plugin API.
- A moderation policy, complaint process, or a claim of DSA compliance.
- Tested server-database backup/restore paths.

### Upgrade notes

Back up an existing SQLite instance before upgrading. Run `novariusirc database
upgrade --instance NAME` only while the bot is stopped; Novarius upgrades a
copy, validates it, and atomically replaces the live database only on success.
