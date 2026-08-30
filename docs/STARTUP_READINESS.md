# Startbereitschaft, Module und Plugins

Stand: 30. August 2026

Dieses Dokument hält den technischen Stand am Ende der Stabilisierungsrunde
fest. Es trennt bereits funktionierende Bestandteile von noch offenen Arbeiten
für einen normalen Start mit eingebauten Modulen und externen Plugins.

Das ursprünglich geplante optionale FragDenStaat-Plugin wurde in dieser Runde
noch nicht umgesetzt. Der Wiedereinstieg dafür ist am Ende des Dokuments
festgehalten, damit die nächste Sitzung wieder beim eigentlichen Plugin beginnt.

## Kurzbewertung

Ein normaler Start mit dem eingebauten RSS-Modul und einem explizit aktivierten
externen Plugin ist als MVP möglich. Die Grundlage ist testbar und
funktionsfähig, aber noch keine vollständig verwaltbare Pluginplattform.

Am 30. August 2026 wurde folgender Stand verifiziert:

- 80 von 80 Tests erfolgreich
- Ruff ohne Befund
- Poetry-Projektmetadaten gültig
- CLI-Hilfe und Versionsausgabe funktionieren
- gemeinsamer Lifecycle-Smoke-Test mit `rss_announcer` und
  `example_greetings` erfolgreich
- Modul und externes Plugin werden geladen, gestartet und wieder entfernt

Der IRC-Integrationstest verwendet einen lokalen Testserver. Ein längerer Test
gegen ein reales IRC-Netz ist dadurch nicht ersetzt.

## Bereits fertig

| Bereich | Stand | Anmerkung |
| --- | --- | --- |
| Konfiguration laden | fertig | Datei, Konfigurationsverzeichnis oder reiner Env-Modus |
| Konfigurations-Includes | fertig | Beispielsweise `secrets.toml`, `feeds.toml` und `moderation.toml` |
| Relative Pfade | fertig | Werden relativ zur Instanzkonfiguration aufgelöst |
| Validierung | fertig | Unbekannte Felder und unsichere Modul-/Pluginnamen werden abgelehnt |
| Core-Commands | fertig | `ping`, `uptime`, `version` und `help` |
| Modul-Auswahl | fertig | Über `[modules].enabled` |
| Plugin-Auswahl | fertig | Explizite Allowlist über `[plugins].load` |
| Plugin-Ablage | fertig | Einzelne Python-Datei oder Paket mit `__init__.py` |
| Plugin-Pfadschutz | fertig | Pfade, dotted imports und Parent-Referenzen werden abgelehnt |
| Plugin-Basisklasse | fertig | Genau eine `BasePlugin`-Unterklasse pro Pluginmodul |
| Plugin-Lifecycle | grundsätzlich fertig | `on_load()` und `on_unload()` |
| Plugin-Hooks | fertig | IRC- und IRCv3-Ereignisse werden als `CommandContext` weitergegeben |
| Gemeinsame CommandRegistry | fertig | Core, Module und Plugins benutzen denselben Dispatcher |
| Aliase | fertig | Werden registriert und auf Kollisionen geprüft |
| Rollen | fertig | `user`, `admin` und `owner` |
| Rate-Limit | fertig | Gilt auch für Plugincommands |
| Plugincommands in `help` | fertig | Rollenabhängig sichtbar |
| Fehler in Commands und Hooks | fertig | Werden abgefangen und protokolliert |
| Fehler beim Pluginladen | fertig | Start bricht sichtbar ab; bereits geladene Plugins werden entfernt |
| Plugin-Unload | fertig | Commands, Aliase, Hooks und Import werden entfernt |
| IRC-Ereignisqueue | fertig | Begrenzt und vom Protokollleser getrennt |
| IRCv3-`server-time` im Kontext | fertig | Als zeitzonenbewusstes UTC-`datetime` verfügbar |
| RSS-Modul | funktionsfähig | Feedregistrierung, Polling, Commands und Ankündigungen |
| Moderation | funktionsfähig | Zentraler Core-Service; das alte Modul ist nur noch ein Kompatibilitätshinweis |
| Graceful Shutdown | fertig | SIGINT/SIGTERM sowie Feeds, Plugins und Worker werden behandelt |
| Container-Grundlage | vorhanden | Python 3.12 und unprivilegierter Laufzeitbenutzer |

Wichtige Implementierungen:

- `novariusirc/__main__.py`: Startreihenfolge und Shutdown
- `novariusirc/core/plugins.py`: Module, externe Plugins und Hooks
- `novariusirc/core/commands.py`: Registrierung, Rollen, Aliase und Dispatch
- `novariusirc/core/client.py`: IRC-/IRCv3-Anbindung und Ereignisqueue
- `docs/PLUGINS.md`: derzeitige öffentliche Pluginbeschreibung

## Noch offen

| Priorität | Bereich | Offener Punkt |
| --- | --- | --- |
| hoch | Start-Bootstrap | Verständliche Startfehler statt möglicher Python-Tracebacks |
| hoch | Konfigurationsprüfung | `--check-config` für Secrets, Pfade, Zeitzone, Module und Plugins ohne IRC-Verbindung |
| hoch | Lifecycle-Absicherung | Timeouts und Rollback bei fehlerhaftem `start()`, `stop()` oder `on_unload()` |
| hoch | Startreihenfolge | Externe `on_load()`-Hooks laufen derzeit vor dem `start()` eingebauter Module |
| hoch | Plugin-Tasks | Keine zentrale Registrierung, Überwachung und Beendigung eigener Hintergrundtasks |
| hoch | Plugin-Abhängigkeiten | Keine deklarative Prüfung zusätzlicher PyPI-Pakete |
| mittel | Zentrale Metadaten | Manifest für Name, Version, Beschreibung, Autor, Abhängigkeiten und API-Kompatibilität fehlt |
| mittel | Einheitliche Identität | Konfigurationsname und interner Pluginname können voneinander abweichen |
| mittel | Plugin-Konfiguration | Einstellungen liegen noch unter `plugins.settings`; separate Plugin-Dateien fehlen |
| mittel | Plugin-/Modulliste | Kein Bot- oder CLI-Command für Laufzustand und Metadaten |
| mittel | Reload | Keine öffentliche Schnittstelle zum Laden, Entladen oder Neuladen |
| mittel | Einheitliche API | Eingebaute Module und externe Plugins verwenden noch verschiedene Basisklassen |
| mittel | Account-Rollen | IRC-Services-Accounts werden erfasst, aber noch nicht zentral Rollen zugeordnet |
| mittel | TOTP-Bedienung | Prüfung ist vorhanden, ein eingebauter Login-/Auth-Command fehlt |
| mittel | Logstruktur | Core-, IRC-, Channel-, PM-, Raw- und Moderationslogs sind noch nicht sauber getrennt |
| mittel | Ereigniszeit im Log | IRCv3-`server-time` wird noch nicht für Channel- und PM-Logzeitstempel verwendet |
| mittel | Zeitzone | `Europe/Berlin`, CET/CEST-Ausgabe und eine garantierte Zeitzonendatenquelle fehlen |
| mittel | Channelnamen | Konservative Unicode-/Sonderzeichen-Policy samt Dokumentation fehlt |
| niedrig | Control-Shell | Unix-Socket, SSH-Anmeldung und reine Botcommand-Shell sind nur vorgemerkt |
| niedrig | Terminal-/Statusmodus | `-t` und `-s` sind weiterhin reserviert |
| grundsätzlich | Plugin-Vertrauen | Externe Plugins laufen als vertrauenswürdiger Code im Botprozess |

## Unabhängige Arbeitspakete

Die nächsten Arbeiten können in getrennten, überschaubaren Blöcken erfolgen:

1. Start-Bootstrap und `--check-config`
2. Logging, Zeitzone und IRCv3-`server-time`
3. Einheitliches Metadatenmodell für Module und Plugins
4. Separate Plugin-Konfigurationen
5. Robuster Lifecycle mit Taskverwaltung, Timeouts und Rollback
6. `plugins list`, `status`, `reload` und passende Hilfe
7. Accountbasierte Rollen und eingebauter TOTP-Login
8. Container-Härtung und eigener Python-3.12-Container-Test
9. Später eine Control-Shell über Unix-Socket beziehungsweise SSH

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

Als portable Datenquelle wurde das offizielle PyPI-Paket `tzdata` in Betracht
gezogen. Pendulum beziehungsweise Arrow bleiben lediglich eine spätere
Überlegung für umfangreichere Kalender-, Intervall- und Pluginfunktionen.

### Control-Shell

Die moderne Alternative zu Eggdrops DCC-Partyline soll keine Betriebssystem-
Shell sein. Vorgemerkt ist eine authentifizierte Shell, die ausschließlich
registrierte Botcommands ausführt:

```text
SSH oder Unix-Socket
        ↓
CommandRegistry
        ↓
Botantwort
```

SSH-Schlüssel und optional sicher gehashte Passwörter wären mögliche
Anmeldearten. SFTP, SCP, Portweiterleitung, beliebige Prozesse und eine echte
BusyBox-Shell sollen darüber nicht verfügbar sein. AsyncSSH wurde nur als
mögliche spätere Abhängigkeit betrachtet und noch nicht aufgenommen.

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
