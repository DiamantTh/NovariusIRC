# Startbereitschaft, Module und Plugins

Stand: 31. August 2026

Dieses Dokument hält den technischen Stand am Ende der Stabilisierungsrunde
fest. Es trennt bereits funktionierende Bestandteile von noch offenen Arbeiten
für einen normalen Start mit eingebauten Modulen und externen Plugins.

Plugin-Vorhaben werden hier nur als Abgrenzung geführt. Dieser Checkup bewertet
den Core, eingebaute Module und die lokale Betriebsführung unabhängig davon.

## Kurzbewertung

Ein normaler Start mit dem eingebauten RSS-Modul und einem explizit aktivierten
externen Plugin ist als MVP möglich. Die Grundlage ist testbar und
funktionsfähig, aber noch keine vollständig verwaltbare Pluginplattform.

Am 31. August 2026 wurde folgender Stand verifiziert:

- 142 von 142 Tests einschließlich lokalem IRC-Integrationstest erfolgreich
- Ruff ohne Befund
- Poetry-Projektmetadaten gültig
- CLI-Hilfe und Versionsausgabe funktionieren
- gemeinsamer Lifecycle-Smoke-Test mit `rss_announcer` und
  `example_greetings` erfolgreich
- Modul und externes Plugin werden geladen, gestartet und wieder entfernt
- `--check-config`, `--status`, Terminal-Konsole und Unix-Control-Socket sind
  ohne IRC-Verbindung beziehungsweise ohne TCP-Listener verfügbar

Der IRC-Integrationstest verwendet einen lokalen Testserver. Ein längerer Test
gegen ein reales IRC-Netz ist dadurch nicht ersetzt.

## Bereits fertig

| Bereich | Stand | Anmerkung |
| --- | --- | --- |
| Konfiguration laden | fertig | Datei, Konfigurationsverzeichnis oder reiner Env-Modus |
| Konfigurations-Includes | fertig | Beispielsweise `secrets.toml`, `feeds.toml` und `moderation.toml` |
| Relative Pfade | fertig | Werden relativ zur Instanzkonfiguration aufgelöst |
| Validierung | fertig | Unbekannte Felder und unsichere Modul-/Pluginnamen werden abgelehnt |
| Core-Commands | fertig | `ping`, `uptime`, `version`, `botinfo` und `help`; im Channel nur gezielte Nick-Ansprache, in Query/Local ohne Botnamen |
| Modul-Auswahl | fertig | Über `[modules].enabled` |
| Plugin-Auswahl | fertig | Explizite Allowlist über `[plugins].load` |
| Plugin-Ablage | fertig | Einzelne Python-Datei oder Paket mit `__init__.py` |
| Plugin-Pfadschutz | fertig | Pfade, dotted imports und Parent-Referenzen werden abgelehnt |
| Plugin-Basisklasse | fertig | Genau eine `BasePlugin`-Unterklasse pro Pluginmodul |
| Plugin-Lifecycle | grundsätzlich fertig | `on_load()` und `on_unload()` |
| Plugin-Hooks | fertig | IRC- und IRCv3-Ereignisse werden als `CommandContext` weitergegeben |
| Gemeinsame CommandRegistry | fertig | Core, Module und Plugins benutzen denselben Dispatcher |
| Aliase und Commandnamen | fertig | Global eindeutig, case-insensitiv und vor jeder atomaren Registrierung auf Kollisionen geprüft |
| Rollen | fertig | `user`, `admin` und `owner` |
| Rate-Limit | fertig | Gilt auch für Plugincommands |
| Plugincommands in `help` | fertig | Rollenabhängig sichtbar |
| Fehler in Commands und Hooks | fertig | Werden abgefangen und protokolliert |
| Fehler beim Pluginladen | fertig | Start bricht sichtbar ab; bereits geladene Plugins werden entfernt |
| Plugin-Unload | fertig | Commands, Aliase, Hooks und Import werden entfernt |
| IRC-Ereignisqueue | fertig | Begrenzt und vom Protokollleser getrennt |
| Interner IRC-Kern | betriebsfähig getrennt | Protokoll, Zustand, CAP, Eingangsmetadaten, Line-Reader, Wire-Erzeugung und Sendefluss liegen unabhängig unter `novariusirc.irc` |
| IRCv3-Drafts | fertig abgegrenzt | `draft/*`-Capabilities stehen getrennt und bleiben bis zum expliziten Opt-in deaktiviert |
| Account-Tag-Vertrauen | fertig | Accountdaten ändern Identität nur bei tatsächlich ausgehandeltem `account-tag` |
| IRCv3-Batches | fertig | Begrenzte, verschachtelbare BATCH-Lebenszyklen mit Prüfung unbekannter und doppelter Referenzen |
| IRCv3-Standardantworten | fertig | `FAIL`, `WARN` und `NOTE` werden strukturiert ausgewertet und protokolliert |
| CTCP-Basis | fertig | `ACTION`, `PING`, `CLIENTINFO` und immer aktive native Bot-/Buildversion; nur ein sicherer Zusatztext ist konfigurierbar |
| IRC-Eingangsgrenzen | fertig | Eigenständiger Reader mit Idle-Timeout sowie Behandlung unvollständiger und übergroßer Frames |
| IRCv3-`server-time` im Kontext | fertig | Als zeitzonenbewusstes UTC-`datetime` verfügbar |
| RSS-Modul | funktionsfähig | Feedregistrierung, Polling, Commands und Ankündigungen |
| Moderation | funktionsfähig | Zentraler Core-Service; das alte Modul ist nur noch ein Kompatibilitätshinweis |
| Graceful Shutdown | fertig | SIGINT/SIGTERM sowie Feeds, Plugins und Worker werden behandelt |
| Lokale Terminal-Konsole | fertig | `-t` führt registrierte Botcommands als lokaler Owner aus, ohne DCC oder TCP |
| Lokale Einmalbefehle | fertig | `--ctl "!status"` nutzt den optionalen Unix-Socket und gibt nur die Command-Antwort aus |
| Control-Socket | fertig | Optional über `[control]`, Rechte `0600`, kein TCP-Listener und keine Betriebssystem-Shell |
| Container-Grundlage | vorhanden | Python 3.12 und unprivilegierter Laufzeitbenutzer |

Wichtige Implementierungen:

- `novariusirc/__main__.py`: Startreihenfolge und Shutdown
- `novariusirc/core/plugins.py`: Module, externe Plugins und Hooks
- `novariusirc/core/commands.py`: Registrierung, Rollen, Aliase und Dispatch
- `novariusirc/irc/`: unabhängige IRC-/IRCv3-Primitiven
- `novariusirc/core/client.py`: Bot-Adapter und Ereignisqueue
- `docs/PLUGINS.md`: derzeitige öffentliche Pluginbeschreibung

## Noch offen

| Priorität | Bereich | Offener Punkt |
| --- | --- | --- |
| erledigt | Start-Bootstrap | Konfigurations- und Startfehler werden in der CLI ohne Traceback ausgegeben |
| erledigt | Konfigurationsprüfung | `--check-config` prüft Core-Konfiguration, TLS-Dateien und eingebaute Module ohne IRC-Verbindung; externe Plugins sind bewusst ausgenommen |
| erledigt | Lifecycle-Absicherung | Eingebaute Module haben Start-/Stop-Timeouts, Rollback und zentral überwachte Hintergrundtasks |
| hoch | Startreihenfolge | Externe `on_load()`-Hooks laufen derzeit vor dem `start()` eingebauter Module |
| hoch | Plugin-Tasks | Keine zentrale Registrierung, Überwachung und Beendigung eigener Hintergrundtasks |
| hoch | Plugin-Abhängigkeiten | Keine deklarative Prüfung zusätzlicher PyPI-Pakete |
| mittel | Zentrale Metadaten | Manifest für Name, Version, Beschreibung, Autor, Abhängigkeiten und API-Kompatibilität fehlt |
| mittel | Einheitliche Identität | Konfigurationsname und interner Pluginname können voneinander abweichen |
| mittel | Plugin-Konfiguration | Einstellungen liegen noch unter `plugins.settings`; separate Plugin-Dateien fehlen |
| erledigt | Modulstatus | `!status` zeigt Verbindungszustand, Netzwerk, aktive eingebaute Module und Feed-Zustand |
| mittel | Reload | Keine öffentliche Schnittstelle zum Laden, Entladen oder Neuladen |
| mittel | Einheitliche API | Eingebaute Module und externe Plugins verwenden noch verschiedene Basisklassen |
| mittel | Operator-/Rechteverwaltung | `user`, `admin` und `owner` existieren; persistente interne Operatoren, DB-Rechte und einmaliges Container-Bootstrap fehlen noch |
| Entscheidung offen | TOTP-Bedienung | Prüfung und Sitzungsverwaltung sind als optionaler Baustein vorhanden; ein Login-/Auth-Command wird erst nach Festlegung des gewünschten Bedienwegs gebaut |
| erledigt | Logstruktur | Core-Logs sowie IRC-Channel-, PM- und Raw-Logs liegen getrennt unter `core/` beziehungsweise `irc/<network>/...` |
| erledigt | Ereigniszeit im Log | IRCv3-`server-time` wird für Channel- und PM-Ereignisse verwendet, wenn der Server einen gültigen Zeit-Tag liefert |
| erledigt | Zeitzone | `Europe/Berlin` ist konfigurierbar und für IRC-Textlogs aktiv; `tzdata` stellt die Daten auch in Minimalcontainern bereit |
| erledigt | Channelnamen | Konservative Unicode-Policy mit expliziter Kompatibilitätsfreigabe für ungewöhnliche Zeichen |
| teilweise erledigt | Control-Shell | Lokaler Unix-Socket mit Dateirechten `0600` und reiner Botcommand-Shell ist fertig; ein möglicher SSH-Zugang ist weiterhin nur vorgemerkt |
| erledigt | Terminal-/Statusmodus | `-s`/`--status` zeigt die lokale Instanzkonfiguration ohne IRC-Verbindung; `-t` startet eine lokale, nicht über DCC oder TCP erreichbare Owner-Konsole |
| grundsätzlich | Plugin-Vertrauen | Externe Plugins laufen als vertrauenswürdiger Code im Botprozess |

## Unabhängige Arbeitspakete

Die nächsten Arbeiten können in getrennten, überschaubaren Blöcken erfolgen:

1. Persistente interne Operatoren und Rollen mit einmaligem ENV-Bootstrap bauen
2. Bedienweg für den optionalen TOTP-Baustein festlegen
3. Container-Härtung und einen eigenen Python-3.12-Container-Test ergänzen
4. Optional SSH-Zugang zur bereits vorhandenen lokalen Command-Shell

Die übrigen Punkte in der offenen Tabelle betreffen die Pluginplattform und
sind bewusst nicht Teil dieses Core-Checkups.

Für einen ersten realen Belastungstest fehlen keine fundamentalen
Startbestandteile. Er setzt eine gültige Instanzkonfiguration mit echten
Zugangsdaten und ausschließlich vorhandenen, vertrauenswürdigen Plugins voraus.

## Festgehaltene Architekturentscheidungen

### Module und externe Plugins

- Eingebaute Module sind zentral gepflegte Projektbestandteile unter
  `novariusirc/modules/`.
- Externe Plugins liegen im Instanzverzeichnis unter `plugins/`.
- Das bloße Ablegen einer Datei lädt sie nicht; die Konfiguration muss das
  Plugin ausdrücklich freigeben.
- Kleine und große Plugins werden nicht künstlich in verschiedene
  Pluginarten aufgeteilt.
- Externe Plugins sind derzeit vertrauenswürdiger Python-Code und keine
  Sandbox-Anwendungen.

### Zukünftige Konfiguration

Die Hauptkonfiguration soll sauber bleiben. Als noch nicht umgesetztes Ziel
wurde eine Struktur in dieser Art festgehalten:

```text
instance/
├── config.toml
├── config/
│   ├── feeds.toml
│   ├── moderation.toml
│   └── plugins/
│       └── fragdenstaat.toml
├── plugins/
│   └── fragdenstaat/
├── data/
└── logs/
```

Fest vorgegebene API-Standardwerte wie die öffentliche FragDenStaat-Basis-URL
sollten im Plugin liegen. Die Instanzkonfiguration soll nur echte
Betreiberentscheidungen beziehungsweise bewusste Overrides enthalten.

### Channelnamen

- Channel-Präfixe werden anhand des vom IRCd angekündigten `CHANTYPES`
  erkannt.
- Regulär unterstützt werden Unicode-Buchstaben, Zahlen, Bindestrich und
  Unterstrich; deutsche Zeichen wie `ä`, `ö`, `ü` und `ß` gehören dazu.
- Ungewöhnliche Zeichen wie `/` oder `\\` sollen standardmäßig abgelehnt
  werden und nur über eine ausdrücklich aktivierte Kompatibilitätsoption
  zugelassen werden.
- Eine solche Freigabe wäre nur eingeschränkt unterstützt und müsste in
  Konfiguration und Dokumentation deutlich erklärt werden.

### Logging und Zeit

Normale IRC-Logs sollen menschenlesbar bleiben:

```text
[18:42:13] <Thomas> Hallo zusammen
[18:42:28] * Thomas testet den Bot
[18:43:02] --ChanServ-- Channel modes changed
[18:43:17] *** Peter hat #novariusirc betreten
```

Vorgesehene Trennung:

```text
logs/
├── core/
├── irc/<network>/channels/
├── irc/<network>/private/
├── irc/<network>/raw/
└── moderation/
```

Bei ausgehandelter IRCv3-Capability `server-time` und vorhandenem gültigem
`time`-Tag soll der Ereigniszeitpunkt verwendet werden. Ohne Tag oder ohne
ausgehandelte Capability gilt die Empfangszeit. Für lesbare Logs ist eine
instanzweite Ausgabe in `Europe/Berlin` vorgesehen; intern bleibt die Zeit
zeitzonenbewusst.

Das offizielle PyPI-Paket `tzdata` ist als reguläre Abhängigkeit enthalten,
damit die IANA-Zeitzonendaten auch in Minimalcontainern verfügbar sind.
Pendulum beziehungsweise Arrow bleiben lediglich eine spätere Überlegung für
umfangreichere Kalender- und Intervallfunktionen.

### Control-Shell

Die moderne Alternative zu Eggdrops DCC-Partyline ist keine Betriebssystem-
Shell. Der lokale Unix-Socket ist optional über `[control]` aktivierbar,
erhält die Dateirechte `0600` und führt ausschließlich registrierte
Botcommands als lokaler Owner aus:

```text
Unix-Socket (umgesetzt), später optional SSH
        ↓
CommandRegistry
        ↓
Botantwort
```

Der lokale Aufruf erfolgt über `novariusirc --ctl "!status" --config ...`.
SSH-Schlüssel und optional sicher gehashte Passwörter wären für einen späteren
SSH-Zugang mögliche Anmeldearten. SFTP, SCP, Portweiterleitung, beliebige
Prozesse und eine echte BusyBox-Shell sollen darüber nicht verfügbar sein.
AsyncSSH wurde nicht aufgenommen.

Eine tatsächliche Wartungsshell gehört ausschließlich in die abgeschottete
Containerumgebung und wäre beispielsweise über `podman exec` erreichbar.

## Wiedereinstieg: FragDenStaat

Die nächste Sitzung sollte wieder beim ursprünglichen Ziel beginnen: einem
optionalen, lesenden FragDenStaat-Plugin für öffentliche Informationen.

Vorgesehener Umfang:

- öffentliche Anfragen suchen
- Suchergebnisse kompakt im IRC darstellen
- einzelne öffentliche Anfragen lesen
- Status, zuständige Stelle und öffentliche Metadaten anzeigen
- vorhandene öffentliche Nachrichten beziehungsweise Dokumenthinweise lesen,
  soweit die API dies anbietet
- Pagination und sinnvolle Ergebnisgrenzen
- Timeouts, Rate-Limits und verständliche API-Fehler
- keine schreibenden oder authentifizierten Vorgänge in der ersten Version

Erste Schritte für diese neue Runde:

1. OpenAPI-/Swagger-Schema vollständig anhand der Operationen auswerten.
2. Nur die öffentlichen, lesenden Endpunkte in einer kleinen Matrix erfassen.
3. Ein Pluginmanifest und eine separate Beispielkonfiguration festlegen.
4. Commands wie `!fds search`, `!fds request` und gegebenenfalls
   `!fds messages` entwerfen.
5. Erst danach das Plugin unter `plugins/fragdenstaat/` implementieren.

Die zu prüfenden Ausgangspunkte sind:

- <https://fragdenstaat.de/api/v1/schema/swagger-ui/>
- <https://fragdenstaat.de/api/>
