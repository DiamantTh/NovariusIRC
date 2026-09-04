# Betriebsstand und nächste Entwicklungsstufen

Stand: 1. September 2026

Dieses Dokument trennt den nutzbaren Core-/Modulbetrieb von noch offenen
Release-Arbeiten und späteren Konzepten. Externe Plugins, eine öffentliche
Weboberfläche und der Moderationsausbau sind nicht Teil des heutigen
Betriebsversprechens.

## Kurzbewertung

Der IRC-Core ist für einen kontrollierten Einzelinstanzbetrieb nutzbar: eine
Instanz verbindet sich mit einem IRC-Netz, beantwortet Core-Befehle und kann
das eingebaute RSS/Atom-Modul ausführen. Konfiguration, lokaler Control-Socket,
Buildinformationen und Protokollgrenzen sind getestet.

Vor einem als stabil beworbenen Release fehlen noch automatisierte
Release-Absicherung und dokumentierte Tests auf realen IRC-Netzen. Persistente
Core-Daten, Backups und die Offline-Wiederherstellung sind vorhanden.

Verifiziert am 4. September 2026:

- 192 von 192 Tests einschließlich lokalem IRC-Integrationstest erfolgreich
- Ruff ohne Befund und Poetry-Metadaten gültig
- `config check`, `config status`, `database init` und `database check`
  funktionieren ohne IRC-Verbindung
- Konfigurationsreferenz liegt auf Deutsch und Englisch vor

Ein lokaler Integrationstest ersetzt keinen längeren Test mit einem realen
IRC-Netz und dessen Services.

## Bereits betriebsfähig

| Bereich | Stand | Anmerkung |
| --- | --- | --- |
| IRC-Core | fertig | Reconnect, TLS, CAP, SASL, IRCv3-Ereignisse, Sendebegrenzung und getrennte Ereignisqueue |
| Alte IRCds | fertig | IRCv3 ist optional; ohne CAP und Account-Tag bleibt der normale IRC-Betrieb möglich |
| Konfiguration | fertig | TOML, Includes, ENV-Overrides, strikte Schlüsselprüfung und relative Pfade |
| Lokale Steuerung | fertig | Terminal-Konsole und Unix-Socket mit `0600`, ohne TCP-Listener oder Betriebssystem-Shell |
| Rollen | fertig | DB-bindbare Rollen für Hostmask, IRCv3-Account oder CertFP; einmaliger Owner-Seed und Owner-Befehl `role` |
| SQLite-Backups | fertig | Konsistenter Snapshot, Datenarchiv, SHA-256-Manifest, Botname und UTC-Dateiname; bewusster Offline-Restore, optional bzip3 |
| Buildinformation | fertig | `-v`, `-V`, `--version`, IRC-`version` und `botinfo` |
| Sprache | fertig | Core- und Modulantworten für Deutsch, Englisch und Japanisch |
| RSS/Atom | fertig | Polling, ETag/Last-Modified, Limits und Vorlagen; mit Datenbank liegt der Feed-Status in SQL statt in JSON-Dateien |
| Logging | fertig | Core-, IRC-, Raw- und Moderationslogs; Zeitzone konfigurierbar |
| Datenbankbasis | fertig | SQLAlchemy Core, mitgelieferte Alembic-Revisionen, stabiler Botname, explizite Initialisierung, sichere SQLite-Kopie-vor-Upgrade, WAL, Foreign Keys, Integritäts- und Schemacheck |

## Vor einem Release noch erforderlich

### P0 – Betriebsdaten und Wiederherstellung

Keine offenen Punkte für den derzeit unterstützten SQLite-Betrieb. Spätere
getestete Server-Backends benötigen eigene Dump- und Restorepfade; SQLite-
Archive dürfen nie als angeblich portable Server-Dumps ausgegeben werden.

### P0 – Release-Absicherung

1. Reproduzierbare lokale Prüfungen für Python 3.12 und das Container-Image
   dokumentieren. Es werden bewusst keine Forgejo-Runner oder Push-/PR-Jobs
   betrieben.
2. Release-Notizen als veröffentlichte Fassung, unterstützte Upgradepfade und
   ein reproduzierbares Build-/Installationsverfahren festlegen.
3. Einen dokumentierten Testlauf gegen mindestens ein modernes und ein
   klassisches IRC-Netz durchführen.

## Bereits geplant, aber nicht Release-Voraussetzung

- Die lokale, rein lesende Tornado-API liefert `/_health`, `/_ready` und
  `/v1/status`. Sie bleibt ohne Panel und ohne schreibende HTTP-Endpunkte.
  Später können DB-Schema und letzter erfolgreicher Backup-Lauf hinzukommen.
- Plugin-Worker als Childprozesse: Fehlerisolation überall; optionale stärkere
  Containerhärtung, aber kein Unix-User-Zwang im normalen Betrieb.
- Persistente Moderationsaktionen mit verständlichen Gründen als Grundlage für
  spätere Evidence- und Einspruchsabläufe. Das ist keine DSA-Zusage.
- Getestete Serverdatenbanken, öffentliche API-Authentifizierung, OpenAPI und
  ein Webinterface bleiben eigenständige spätere Vorhaben.

## Bewusste Entscheidungen

- Die Datenbank ist pro Botinstanz getrennt. Der stabile `[bot].name` bestimmt
  standardmäßig `data/<Botname>.sqlite3` und spätere Backupdateien; der
  Laufzeitnick ist dafür nicht maßgeblich.
- SQLite ist der nutzbare Startpunkt. PostgreSQL, MariaDB, MySQL und Microsoft
  SQL Server sind nur registrierte Namen, bis ihre SQLAlchemy-Treiber und
  Migrationspfade getestet sind.
- Alembic-Revisionen werden mit dem Paket ausgeliefert. Eine bestehende
  SQLite-Datei wird nur durch den expliziten Upgradepfad auf einer Kopie
  migriert und danach atomar ersetzt. Die frühere SQLite-Metadatendatei wird
  dabei in die erste Alembic-Revision überführt.
- Bei aktivierter Datenbank sind die DB-Bindungen maßgeblich. Der einmalige
  Owner-Seed kann Hostmasks (klassisches IRC), IRCv3-Accounts oder CertFPs
  enthalten; der danach laufende `role`-Befehl verwaltet die Einträge.
- Secrets bleiben in ENV, Secret-Dateien oder Container-Secrets; sie gehören
  nicht in die Datenbank oder in Backups im Klartext.
- Große Anhänge und Logs bleiben Dateien. Die Datenbank speichert später nur
  strukturierte Zustände und Metadaten.

## Startablauf heute

1. Instanzordner `config/` mit `config.toml`, optionalen Include-Dateien und
   Secrets erstellen.
2. Konfiguration prüfen:

   ```console
   novariusirc config check --config ./config
   ```

3. Falls `[database].enabled = true` gesetzt ist, die SQLite-Datei einmalig
   erzeugen und anschließend prüfen:

   ```console
   novariusirc database init --config ./config
   novariusirc database check --config ./config
   ```

4. Instanz starten und den lokalen Status prüfen:

   ```console
   novariusirc --config ./config
   novariusirc config status --config ./config
   ```

5. Produktive Daten nur mit regelmäßigen extern abgelegten Backups betreiben.
