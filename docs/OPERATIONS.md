# Betrieb

Diese Anleitung beschreibt eine einzelne NovariusIRC-Instanz. Jeder Bot läuft
als eigener Prozess oder eigener Container und besitzt sein eigenes
Konfigurations-, Daten-, Log- und Backup-Verzeichnis.

## Lokale Prüfung vor dem Start

```console
poetry install
poetry run pytest -q
poetry run ruff check novariusirc tests
poetry check
poetry build
```

Der Container wird bewusst lokal gebaut; das Projekt nutzt keine Forgejo-Runner:

```console
podman build -t novariusirc:local .
podman run --rm novariusirc:local --version
```

## Erstinstallation mit SQLite

1. `config.example.toml` als `config.toml` kopieren und IRC-Zugangsdaten setzen.
2. Einen stabilen `[bot].name` setzen.
3. Datenbank und mindestens eine einmalige Owner-Bindung konfigurieren, etwa
   per `NOVARIUSIRC_OWNER_HOSTMASK`.
4. Initialisieren und prüfen:

   ```console
   novariusirc --init-database --config ./config.toml
   novariusirc --check-config --config ./config.toml
   novariusirc --check-database --config ./config.toml
   ```

5. Starten:

   ```console
   novariusirc --config ./config.toml
   ```

Relative Pfade gelten relativ zu `config.toml`. Das Verzeichnis des laufenden
Benutzers muss Schreibrechte für `paths.log_root`, `paths.data_root`, den
Control-Socket und – falls aktiv – `backups.directory` haben.

## systemd

Beispiel für eine Instanz unter `/srv/novariusirc/example` als Nutzer
`novariusirc`:

```ini
[Unit]
Description=NovariusIRC example
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=novariusirc
Group=novariusirc
WorkingDirectory=/srv/novariusirc/example
Environment=NOVARIUSIRC_OWNER_HOSTMASK=owner!*@trusted.example
ExecStart=/usr/local/bin/novariusirc --config /srv/novariusirc/example/config.toml
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

`Restart=on-failure` startet nicht nach einem normalen, bewusst ausgelösten
Beenden neu. Secrets gehören in eine nur für den Dienstnutzer lesbare
`EnvironmentFile=` oder in einen Secret-Mechanismus der Umgebung, nicht in die
Unit-Datei.

## Container

Die Konfiguration darf für manuelle Änderungen beschreibbar gemountet werden;
der Bot liest sie nur und schreibt sie nie selbst. Daten, Logs, Backups und der
Unix-Control-Socket brauchen ebenfalls beschreibbare Mounts. Bei Podman mit
SELinux `:Z` ergänzen.

```console
podman run --rm --name example-novariusirc \
  -v ./instance:/app/instance:Z \
  -v ./data:/app/data:Z \
  -v ./logs:/app/logs:Z \
  -v ./backups:/app/backups:Z \
  -v ./run:/app/run:Z \
  -e NOVARIUSIRC_DATA_ROOT=/app/data \
  -e NOVARIUSIRC_LOG_ROOT=/app/logs \
  -e NOVARIUSIRC_OWNER_HOSTMASK='owner!*@trusted.example' \
  novariusirc:local --config /app/instance/config.toml
```

Das mitgelieferte Runtime-Image enthält bzip3. Bei einem eigenen Image muss
`compression = "none"` gewählt werden, falls bzip3 dort fehlt.

Docker-Umgebungsvariablen sind für Laufzeitwerte und Secrets vorgesehen und
werden bei jedem Start eingelesen. Sie werden nicht in die Datenbank
zurückgeschrieben; die einzige absichtliche Ausnahme ist ein Owner-Bootstrap,
der nur bei einer Datenbank ohne Owner-Bindung einmalig greift. Docker-Labels
sind keine Prozessumgebung. Der Bot liest sie bewusst nicht, weil dies Zugriff
auf den Docker-Socket verlangen würde.

## Backup und Offline-Restore

```console
novariusirc --backup-database --config ./config.toml
novariusirc --list-backups --config ./config.toml
```

Vor einer Wiederherstellung den Bot vollständig stoppen. Der Befehl prüft
Manifest und SQLite-Integrität; das Ersetzen der Datenbank verlangt absichtlich
ein eigenes Flag:

```console
novariusirc --restore-database ./backups/BOT_YYYYMMDDTHHMMSSZ.tar \
  --replace-database --restore-data --config ./config.toml
novariusirc --check-database --config ./config.toml
```

`--restore-data` kopiert archivierte Zusatzdateien zurück, löscht aber keine
neueren, nicht archivierten Dateien. Deshalb sollte das Datenverzeichnis vor
einem vollständigen Desaster-Recovery zusätzlich weggesichert werden.
