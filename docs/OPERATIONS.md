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

## Datenbank-Upgrade

Ein normaler Botstart führt absichtlich keine Migration aus. Erkennt
`--check-database` eine ältere Schemarevision, Bot zuerst vollständig stoppen
und dann upgraden:

```console
novariusirc --backup-database --config ./config.toml
novariusirc --upgrade-database --config ./config.toml
novariusirc --check-database --config ./config.toml
```

Für SQLite wird nie die Live-Datei migriert: Novarius erstellt eine
timestampierte `*.pre-migration-*.sqlite3`-Kopie, migriert eine zweite Kopie,
prüft Integrität, Schema und SHA-256 und ersetzt die Live-Datei erst danach
atomar. Die Vor-Migrationskopie bleibt zur Wiederherstellung erhalten. Es muss
mindestens ungefähr die doppelte Größe der Datenbank inklusive WAL frei sein.

## systemd

Beispiel für eine Instanz unter
`/home/novariusirc/NovariusIRC/instances/example` als Nutzer `novariusirc`:

```ini
[Unit]
Description=NovariusIRC example
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=novariusirc
Group=novariusirc
WorkingDirectory=/home/novariusirc/NovariusIRC/instances/example
Environment=NOVARIUSIRC_OWNER_HOSTMASK=owner!*@trusted.example
ExecStart=/home/novariusirc/NovariusIRC/bin/novariusirc --config /home/novariusirc/NovariusIRC/instances/example/config.toml
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

Das Image benutzt dieselbe Präfixstruktur wie der Installer, nur unter `/app`:
`/app/bin`, `/app/venv` und `/app/instances`. Dauerhafte Instanzen liegen
vollständig unter `/app/instances`; relative Pfade in einer Instanz bleiben
damit zusammen. Der Bot erzeugt beim ersten Start einer leeren Instanz deren
Vorlage selbst.

`compose.yml` ist absichtlich hostneutral und nutzt ein benanntes Volume. Es
funktioniert direkt als Portainer-Stack aus dem Repository sowie mit Docker
oder Podman Compose:

```console
podman compose up --build
```

Ein Bind-Mount oder ein Kubernetes-PVC darf stattdessen nach
`/app/instances` zeigen. Der Quellpfad ist dabei eine Entscheidung des
jeweiligen Hosts und steht deshalb nicht in der versionierten Compose-Datei.
Bei einem Bind-Mount müssen die Dateien für UID/GID `10001` schreibbar sein;
bei Podman mit SELinux `:Z` ergänzen.

Beispiel für einen direkten, hostseitig gewählten Bind-Mount:

```console
podman run --rm --name example-novariusirc \
  -v /chosen/instance-root:/app/instances:Z \
  -e NOVARIUSIRC_INSTANCE=example \
  -e NOVARIUSIRC_OWNER_HOSTMASK='owner!*@trusted.example' \
  novariusirc:local
```

Das mitgelieferte Runtime-Image enthält bzip3. Bei einem eigenen Image muss
`compression = "none"` gewählt werden, falls bzip3 dort fehlt.

Container-Umgebungsvariablen sind für Laufzeitwerte und Secrets vorgesehen und
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
