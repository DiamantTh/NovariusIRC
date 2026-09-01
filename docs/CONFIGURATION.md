# Konfigurationsreferenz

**Sprachen:** Deutsch · [English](CONFIGURATION.en.md)

## Inhaltsverzeichnis

- [Laden und prüfen](#loading)
- [Ladereihenfolge und Includes](#includes)
- [Bot](#bot)
- [Netzwerk und IRCv3](#network)
- [Authentifizierung](#auth)
- [Rollen](#roles)
- [Owner-Bootstrap](#owner-bootstrap)
- [Logging](#logging)
- [Befehle, Lifecycle und Control](#commands-lifecycle-control)
- [Eingebaute Module](#modules)
- [Pfade und Worker](#paths-workers)
- [Datenbank](#database)
- [Backups](#backups)
- [Feeds](#feeds)
  - [Feed-Definitionen](#feed-definitions)
- [Moderation](#moderation)
  - [Prüfungen und Verwarnungen](#moderation-checks)
- [Externe Plugins](#plugins)
- [Umgebungsvariablen](#environment)

NovariusIRC verwendet TOML. Die Schlüsselnamen bleiben unabhängig von der
Ausgabesprache Englisch, damit bestehende Konfigurationen, Container-Variablen
und Werkzeuge kompatibel bleiben. Kommentare und diese Referenz sind Deutsch.

Diese Seite folgt dem praktischen Aufbau der
[InspIRCd-Konfigurationsdokumentation](https://docs.inspircd.org/4/configuration/):
Jeder Abschnitt nennt Zweck, Parameter, Standardwerte und ein kurzes Beispiel.
Sie beschreibt die vom aktuellen Core und den eingebauten Modulen ausgewerteten
Werte. Die vollständige Startvorlage ist
[`config.example.toml`](../config.example.toml).

<a id="loading"></a>
## Laden und prüfen

```console
novariusirc --check-config --config ./config.toml
novariusirc --status --config ./config.toml
novariusirc --config ./config.toml
```

`--check-config` verbindet sich nicht mit IRC. Es prüft die TOML-Struktur,
Pflichtwerte, Wertebereiche, referenzierte TLS-Dateien, beschreibbare
Laufzeitpfade und importierbare eingebaute Module.

Als `--config` sind zulässig:

- eine TOML-Datei;
- ein Verzeichnis, in dem dann `config.toml` gesucht wird;
- `env`, `environment` oder `-` für einen Start ausschließlich über
  Umgebungsvariablen.

Alle typisierten Abschnitte verbieten unbekannte Schlüssel. Ein Tippfehler führt
deshalb beim Start zu einem Fehler, statt unbemerkt ignoriert zu werden. Die
freien Tabellen `plugins.settings` und `moderation.channels` sind die bewussten
Ausnahmen.

<a id="includes"></a>
## Ladereihenfolge und Includes

Die effektive Konfiguration entsteht in dieser Reihenfolge:

1. `config.toml` wird geladen.
2. Include-Dateien werden in ihrer angegebenen Reihenfolge rekursiv
   zusammengeführt. Ein späterer Wert überschreibt einen früheren; Listen werden
   vollständig ersetzt.
3. Unterstützte Umgebungsvariablen überschreiben einzelne Werte.
4. Abhängigkeiten zwischen Einstellungen und Laufzeitpfade werden geprüft.

Ohne explizite Include-Angabe wird eine vorhandene `secrets.toml` neben der
Hauptdatei optional geladen. Sobald Includes ausdrücklich angegeben sind, muss
jede genannte Datei existieren.

```toml
[includes]
files = ["secrets.toml", "feeds.toml", "moderation.toml"]
```

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `files` | Textliste | `["secrets.toml"]` | Zusammenzuführende Dateien in Ladereihenfolge; doppelte Namen werden entfernt. |

Alternativ ist die Kurzform auf oberster Ebene möglich:

```toml
include = ["secrets.toml", "feeds.toml"]
```

Include-Pfade sind relativ zum Verzeichnis der Hauptdatei. Absolute Pfade sind
ebenfalls erlaubt. Zugangsdaten gehören in eine nicht versionierte Datei nach
Vorlage von [`secrets.example.toml`](../secrets.example.toml).

<a id="bot"></a>
## `[bot]`

Allgemeine Darstellung und Sprache des Bots.

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `name` | Text | konfigurierter IRC-Nick | Stabiler Instanzname für Daten- und Backup-Dateien; unabhängig vom Nick zur Laufzeit. |
| `prefix` | Text | `!` | Präfix für Befehle in Query und lokaler Steuerung. Im Kanal wird zuerst der Bot-Nick mit `:` oder `,` adressiert; danach ist das Präfix optional. |
| `language` | Text | aus Umgebung, sonst `en` | Ausgabesprache: `de`, `en` oder `ja`. Locale-Formen wie `de_DE.UTF-8` werden normalisiert. |
| `ctcp_version_extra` | Text | leer | Optionaler Zusatz zu CTCP `VERSION`; Produktname und Paketversion bleiben unverändert. Steuerzeichen und mehr als 300 UTF-8-Bytes sind unzulässig. |

Wird `language` weggelassen, gilt die Reihenfolge `NOVARIUSIRC_LANG`,
`LANGUAGE`, `LC_ALL`, `LC_MESSAGES`, `LANG`, danach Englisch.

```toml
[bot]
prefix = "!"
language = "de"
ctcp_version_extra = "Produktivinstanz"
```

<a id="network"></a>
## `[network]`

IRC-Verbindung, Identität und Protokollgrenzen. `server`, `nick`, `user` und
`realname` sind in einer dateibasierten Konfiguration Pflichtwerte.

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `server` | Text | Pflicht | DNS-Name oder IP-Adresse des IRC-Servers. |
| `port` | Ganzzahl | `6667` | TCP-Port von 1 bis 65535. Für TLS wird üblicherweise 6697 verwendet. |
| `tls` | Boolean | `false` | Verschlüsselte TLS-Verbindung aktivieren. SASL und CertFP verlangen derzeit TLS. |
| `bind_ip` | Text oder leer | leer | Lokale Quell-IP für den Verbindungsaufbau. |
| `bind_hostname` | Text oder leer | leer | Lokaler Quell-Hostname; alternativ zu `bind_ip`. |
| `nick` | Text | Pflicht | Gewünschter IRC-Nickname, ohne Leer- oder Steuerzeichen. |
| `user` | Text | Pflicht | Benutzername für `USER`, ohne Leer- oder Steuerzeichen. |
| `realname` | Text | Pflicht | Nichtleerer Realname/GECOS-Text. |
| `channels` | Textliste | `[]` | Beim Verbindungsaufbau zu betretende Kanäle. |
| `name` | Text oder leer | aus `005 NETWORK` | Manueller interner Netzwerkname. |
| `allow_unusual_channel_names` | Boolean | `false` | Erlaubt nach dem Präfix weitere Zeichen als Unicode-Buchstaben, Ziffern, `-` und `_`. |
| `reconnect_delays` | Ganzzahlliste | `[10, 20, 40, 80]` | Positive Wartezeiten in Sekunden für aufeinanderfolgende Neuverbindungen. |
| `connect_timeout_seconds` | Zahl | `30.0` | Zeitlimit für den TCP-/TLS-Verbindungsaufbau; muss größer null sein. |
| `registration_timeout_seconds` | Zahl | `60.0` | Zeitlimit bis zur abgeschlossenen IRC-Registrierung. |
| `idle_timeout_seconds` | Zahl | `300.0` | Maximale Zeit ohne empfangene IRC-Daten vor einem Verbindungsabbruch. |
| `ircv3_enabled` | Boolean | `true` | IRCv3-CAP-Aushandlung aktivieren. Der Bot bleibt mit älteren IRCds kompatibel. |
| `ircv3_capabilities` | Textliste | siehe Vorlage | Stabile gewünschte Capabilities. Nur vom Server angebotene Werte werden angefordert. `sasl` gehört nicht in diese Liste. |
| `ircv3_draft_capabilities` | Textliste | `[]` | Explizite Opt-ins, deren Namen mit `draft/` beginnen müssen. |
| `send_rate_per_second` | Zahl | `1.0` | Nachhaltige Rate ausgehender IRC-Zeilen pro Sekunde. |
| `send_burst` | Ganzzahl | `4` | Kurzzeitig erlaubtes Sende-Burstvolumen, mindestens 1. |
| `send_queue_size` | Ganzzahl | `256` | Maximale Anzahl wartender ausgehender IRC-Zeilen. |
| `event_queue_size` | Ganzzahl | `256` | Maximale Anzahl wartender Anwendungsereignisse. |

Standardpräfixe für Kanäle sind `#`, `&`, `+` und `!`. Leerzeichen, Kommas,
Doppelpunkte sowie CR, LF und NUL bleiben auch im Kompatibilitätsmodus
unzulässig.

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

Authentifizierung des Bot-Clients am IRC-Netz. Alle Verfahren sind
standardmäßig deaktiviert oder wirkungslos, bis sie ausdrücklich konfiguriert
werden.

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `sasl_enabled` | Boolean | `false` | SASL während der IRCv3-Registrierung aktivieren. |
| `sasl_mechanism` | Text | `PLAIN` | Unterstützt werden `PLAIN` und `EXTERNAL`. |
| `sasl_username` | Text oder leer | Bot-Nick bei aktiviertem SASL | SASL-Authentifizierungsname. |
| `sasl_password` | Text oder leer | leer | Passwort für SASL PLAIN. |
| `nickserv_enabled` | Boolean | `false` | Identifizierung per Nachricht an einen Services-Nick aktivieren. |
| `nickserv_service` | Text | `NickServ` | Zielname des Services. |
| `nickserv_username` | Text oder leer | Bot-Nick bei Aktivierung | NickServ-Kontoname. |
| `nickserv_password` | Text oder leer | leer | NickServ-Passwort. |
| `certfp_enabled` | Boolean | `false` | TLS-Clientzertifikat beim IRC-Verbindungsaufbau laden. |
| `certfp_cert_file` | Pfad oder leer | leer | PEM-Zertifikat; für SASL EXTERNAL erforderlich. |
| `certfp_key_file` | Pfad oder leer | leer | Separater privater Schlüssel; leer, wenn er im PEM enthalten ist. |

SASL PLAIN benötigt Benutzername, Passwort und `network.tls = true`. SASL
EXTERNAL benötigt TLS, aktiviertes CertFP und eine Zertifikatsdatei.

<a id="roles"></a>
## `[roles]`

Ohne aktivierte Datenbank werden die Rollen `owner` und `admin` wie bisher
über IRC-Hostmasks aus dieser Konfiguration zugeordnet. Mit Datenbank dienen
`owners` beim ersten Start nur als einmaliger Owner-Seed; `admins` werden dann
nicht mehr verwendet. Weitere Zuweisungen verwaltet ein Owner mit
`!role list`, `!role add` und `!role remove` in der Datenbank.

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `owners` | Rollenliste | `[]` | Einträge mit vollständigen Bot-Rechten. |
| `admins` | Rollenliste | `[]` | Einträge mit erweiterten, aber nicht vollständigen Rechten. |

Jeder Rollen-Eintrag besitzt folgende Felder:

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `hostmask` | Text | Pflicht | Muster `nick!user@host`; `*` und `?` sind Wildcards. |

```toml
[roles]
owners = [
  { hostmask = "owner!*@trusted.example" },
]
admins = [
  { hostmask = "*!staff@*.example" },
]
```

Hostmasks funktionieren auch auf Netzen ohne NickServ und ohne IRCv3. Für
privilegierte Rollen sollten stabile, serverseitig gesetzte Hosts verwendet
werden; ein bloßer Nick ist kein verlässlicher Identitätsnachweis.

<a id="owner-bootstrap"></a>
## `[owner_bootstrap]`

Diese Werte erzeugen einmalig Owner-Bindungen bei der ersten Initialisierung
einer aktivierten Datenbank. Danach merkt die Datenbank den abgeschlossenen
Bootstrap und verwendet diese Werte nie wieder als zweite Autoritätsquelle –
auch nicht, falls später alle Owner-Bindungen entfernt werden. Damit eignet sich
der Abschnitt besonders für die erste Container-Installation.

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `hostmask` | Text oder leer | leer | Hostmask-Muster; funktioniert auch mit klassischen IRCds. |
| `account` | Text oder leer | leer | Exakter IRC-Kontoname aus dem IRCv3-Tag `account`. |
| `certfp` | Text oder leer | leer | Hexadezimaler TLS-Zertifikatsfingerabdruck aus `certfp` oder `solanum.chat/certfp`. Doppelpunkte sind erlaubt. |

```toml
[owner_bootstrap]
hostmask = "owner!*@trusted.example"
# account = "owner-account"
# certfp = "0123456789abcdef..."
```

Für die containerfreundliche Einmal-Konfiguration überschreiben
`NOVARIUSIRC_OWNER_HOSTMASK`, `NOVARIUSIRC_OWNER_ACCOUNT` und
`NOVARIUSIRC_OWNER_CERTFP` die jeweiligen Werte. Mindestens eine Owner-Bindung
ist erforderlich, bevor ein Datenbankbetrieb als startbereit gilt.

<a id="logging"></a>
## `[logging]`

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `level` | Text | `INFO` | Python-Loglevel, beim Laden in Großbuchstaben umgewandelt. |
| `log_dir` | Pfad | `logs` | Kompatibler Logpfad. Ein abweichender Wert wird verwendet, solange `paths.log_root` beim Standard `./logs` bleibt. |
| `timezone` | Text | `Europe/Berlin` | IANA-Zeitzone für lesbare IRC-Logs. |
| `journald_enabled` | Boolean | `false` | Zusätzlich an systemd-journald senden, wenn die optionale Anbindung verfügbar ist. |
| `channel_logging` | Tabellenliste | `[]` | Explizite Auswahl der Kanäle, deren Nachrichten protokolliert werden. |

Ein Eintrag der Tabellenliste besitzt `channel` als Pflichtwert und `enabled`
mit Standard `true`:

```toml
[[logging.channel_logging]]
channel = "#bots"
enabled = true
```

Ohne passenden Eintrag ist das inhaltliche Kanal-Logging ausgeschaltet.

<a id="commands-lifecycle-control"></a>
## `[commands]`, `[lifecycle]` und `[control]`

| Abschnitt.Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `commands.rate_limit_seconds` | Zahl | `2.0` | Mindestabstand für denselben Befehl desselben Benutzers; `0` deaktiviert die Begrenzung. |
| `lifecycle.module_start_timeout_seconds` | Zahl | `30.0` | Zeitlimit zum Start eines eingebauten Moduls. |
| `lifecycle.module_stop_timeout_seconds` | Zahl | `30.0` | Zeitlimit zum Stoppen eines eingebauten Moduls. |
| `control.enabled` | Boolean | `false` | Lokalen Unix-Control-Socket aktivieren. |
| `control.socket_path` | Pfad | `./run/novariusirc.sock` | Socket-Datei; sie wird mit Modus `0600` angelegt. |

Der Control-Endpunkt ist kein TCP-Listener und keine Shell. Er führt dieselben
registrierten Bot-Befehle wie die Terminalsteuerung aus.

<a id="modules"></a>
## `[modules]`

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `enabled` | Textliste | `["rss_announcer"]` | Namen eingebauter Python-Module, in Startreihenfolge. Doppelte Namen werden entfernt. |

`rss_announcer` ist das aktive eingebaute Funktionsmodul. Der alte Name
`moderation` existiert nur als Kompatibilitätshinweis; Moderation ist bereits
ein Core-Dienst und gehört nicht in diese Liste. Ein unbekanntes oder nicht
importierbares Modul lässt `--check-config` fehlschlagen.

<a id="paths-workers"></a>
## `[paths]` und `[workers]`

| Abschnitt.Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `paths.log_root` | Pfad | `./logs` | Stammverzeichnis für Logdateien. |
| `paths.data_root` | Pfad | `./data` | Stammverzeichnis für persistente Laufzeitdaten. Ohne Datenbank liegen Feed-Zustände dort als JSON; mit aktivierter Datenbank liegen sie in SQL. |
| `workers.processes` | Ganzzahl | `2` | Prozessanzahl des Pools für CPU-lastige Aufgaben, mindestens 1. |

Relative Laufzeitpfade werden relativ zum Verzeichnis von `config.toml`
aufgelöst, nicht relativ zum aktuellen Arbeitsverzeichnis. Das betrifft auch
Control-Socket, Moderationslog, Zertifikate und Feed-TLS-Dateien.

<a id="database"></a>
## `[database]`

Die Datenbankschicht ist optional. SQLite ist das erste vollständig nutzbare
Backend. PostgreSQL, MariaDB, MySQL und Microsoft SQL Server sind bereits als
eindeutige Backendnamen registriert, benötigen aber noch ihre Adapter und
werden bis dahin mit einem klaren Fehler abgelehnt.

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `enabled` | Boolean | `false` | Persistente Datenbankschicht aktivieren. |
| `backend` | Auswahl | `sqlite` | `sqlite`, `postgresql`, `mariadb`, `mysql` oder `mssql`; Aliase werden normalisiert. |
| `path` | Pfad oder leer | `<data_root>/<bot.name>.sqlite3` | SQLite-Datei. Der Botname wird für Dateisysteme sicher normalisiert. |
| `dsn` | Text oder leer | leer | Verbindungs-DSN für Serverdatenbanken; vorzugsweise über ENV setzen. Für SQLite unzulässig. |
| `connect_timeout_seconds` | Zahl | `10.0` | Verbindungszeitlimit für Serverdatenbanken, größer null. |
| `busy_timeout_seconds` | Zahl | `5.0` | SQLite-Wartezeit bei konkurrierenden Sperren, mindestens null. |

Eine aktivierte SQLite-Datenbank muss ausdrücklich angelegt werden:

```console
novariusirc --init-database --config ./config.toml
novariusirc --check-database --config ./config.toml
```

Die Initialisierung aktiviert Foreign Keys, WAL, `synchronous = FULL`, führt
die mitgelieferten Alembic-Migrationen aus und speichert den stabilen Botnamen.
Eine unbekannte bestehende SQLite-Datei wird nicht übernommen. Fehlt eine zuvor
initialisierte Datei, bricht der Bot ab, statt unbemerkt eine leere Datenbank
zu erzeugen. Die frühere SQLite-Metadatendatei wird beim expliziten
Initialisieren übernommen und auf die erste Alembic-Revision gesetzt.

<a id="backups"></a>
## `[backups]`

Backups sind optional und werden bewusst nur per CLI gestartet. Die SQLite-Datei
wird mit der SQLite-Backup-API als konsistenter Snapshot gelesen. Zusätzlich
nimmt das Archiv reguläre Dateien unter `paths.data_root` mit, aber nie die
Live-Datenbank, ihre WAL-/SHM-Begleitdateien oder das Backup-Verzeichnis selbst.
`manifest.json` enthält SHA-256 und Größe jeder enthaltenen Datei.

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `enabled` | Boolean | `false` | Erlaubt das Erzeugen von Backups. |
| `directory` | Pfad | `./backups` | Zielverzeichnis; relativ zu `config.toml`. |
| `compression` | Auswahl | `none` | `none` lässt ein portables `.tar`; `bzip3` komprimiert erst ab der Schwelle. |
| `compression_min_bytes` | Ganzzahl | `8388608` | Mindestgröße des TAR vor optionaler bzip3-Kompression. `0` komprimiert immer. |
| `include_data` | Boolean | `true` | Reguläre Zusatzdateien aus `paths.data_root` aufnehmen. |

Die Namen verwenden nur den stabilen Botnamen und UTC, etwa
`MeinBot_20260901T201530Z.tar`:

```console
novariusirc --backup-database --config ./config.toml
novariusirc --list-backups --config ./config.toml
```

Für `compression = "bzip3"` muss `bzip3` im Ausführungspfad installiert sein.
Eine Wiederherstellung ist nur offline möglich und verlangt ausdrücklich
`--replace-database`; `--restore-data` kopiert zusätzlich archivierte
Zusatzdateien zurück:

```console
novariusirc --restore-database ./backups/MeinBot_20260901T201530Z.tar \
  --replace-database --restore-data --config ./config.toml
```

<a id="feeds"></a>
## `[feeds]`

Globale Einstellungen des Feed-Cores. Die Abrufe werden vom eingebauten Modul
`rss_announcer` gestartet, wenn es in `[modules].enabled` enthalten ist.

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `enabled` | Boolean | `true` | Feed-Verarbeitung global aktivieren. |
| `max_feeds` | Ganzzahl | `32` | Maximale Zahl registrierter Feeds. |
| `max_items_per_feed` | Ganzzahl | `64` | Maximale Zahl gemerkter Eintrags-IDs je Feed. |
| `max_items_per_poll` | Ganzzahl | `2` | Globale Obergrenze neuer Meldungen je automatischem Abruf. |
| `max_items_per_manual` | Ganzzahl | `4` | Globale Obergrenze je manuell ausgelöstem Abruf. |
| `refresh_interval` | Ganzzahl | `300` | Abstand automatischer Abrufe in Sekunden. |
| `http_timeout` | Ganzzahl | `10` | HTTP-Zeitlimit in Sekunden. |
| `max_body_size` | Ganzzahl | `262144` | Maximale Antwortgröße in Bytes, mindestens 1024. |
| `user_agents` | Textliste | `[]` | Eigene HTTP-User-Agents. Leer verwendet `NovariusIRC/feeds`. |
| `user_agent_rotate` | Auswahl | `list` | `list` rotiert, `random` wählt zufällig, `fixed` nutzt den ersten Eintrag. |
| `tls_allow_legacy` | Boolean | `false` | Aktiviert die OpenSSL-Option für veraltete Serververbindungen. Nur für notwendige Altserver verwenden. |
| `tls_ca_file` | Pfad oder leer | leer | Eigene CA-Bundle-Datei. |
| `tls_ca_dir` | Pfad oder leer | leer | Verzeichnis eigener CA-Zertifikate. |
| `tls_cert_file` | Pfad oder leer | leer | TLS-Clientzertifikat für Feed-Server. |
| `tls_key_file` | Pfad oder leer | leer | Zugehöriger privater Schlüssel. |
| `feeds` | Tabellenliste | `[]` | Einzelne Feed-Definitionen. |

Leere Strings bei den vier TLS-Pfaden gelten als nicht gesetzt.

<a id="feed-definitions"></a>
### `[[feeds.feeds]]`

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `name` | Text | Pflicht | Anzeigename und interne Bezeichnung. |
| `url` | Text | Pflicht | HTTP(S)-Adresse des RSS-/Atom-Feeds. |
| `channel` | Text oder leer | leer | Einzelnes Ziel; wird zusätzlich in `channels` übernommen. |
| `channels` | Textliste | `[]` | Ein oder mehrere Zielkanäle. Mindestens `channel` oder `channels` ist Pflicht. |
| `enabled` | Boolean | `true` | Einzelnen Feed aktivieren oder pausieren. |
| `template` | Text oder leer | eingebaut | Ausgabevorlage mit `{feed}`, `{title}`, `{summary}`, `{link}` und `{published}`. |
| `min_interval_seconds` | Ganzzahl oder leer | leer | Mindestabstand der Meldungen dieses Feeds; mindestens 0. |
| `per_channel_interval` | Tabelle | `{}` | Mindestabstand je Zielkanal, z. B. `{ "#news" = 900 }`. |
| `max_items_per_poll` | Ganzzahl oder leer | global | Obergrenze je automatischem Abruf. |
| `max_items_per_manual` | Ganzzahl oder leer | global | Obergrenze je manuellem Abruf. |

Eine vollständige Vorlage mit IRC-Formatierung steht in
[`config/feeds.example.toml`](../config/feeds.example.toml).

<a id="moderation"></a>
## `[moderation]`

Moderation ist ein Core-Dienst. Die Prüfungen sind einzeln standardmäßig
deaktiviert; `moderation.enabled = true` allein führt daher noch keine Aktion
aus. Die vollständige Vorlage steht in
[`config/moderation.example.toml`](../config/moderation.example.toml).

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `enabled` | Boolean | `true` | Core-Moderation global zulassen. |
| `log_file` | Pfad | `logs/moderation/moderation.log` | Eigenes rotierendes Entscheidungslog. |
| `rate_limit` | Tabelle | siehe unten | Begrenzung der Nachrichtenrate. |
| `spam` | Tabelle | siehe unten | Erkennung direkt wiederholter Nachrichten. |
| `caps` | Tabelle | siehe unten | Erkennung übermäßiger Großschreibung. |
| `badwords` | Tabelle | siehe unten | RegExp-basierter Inhaltsfilter. |
| `warnings` | Tabelle | siehe unten | Eskalationsschwellen für Verwarnungen. |
| `channels` | Tabelle | `{}` | Rekursive Überschreibungen je Kanal. |

<a id="moderation-checks"></a>
### Prüfungen und Verwarnungen

| Abschnitt.Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `rate_limit.enabled` | Boolean | `false` | Nachrichtenrate prüfen. |
| `rate_limit.messages_per_minute` | Ganzzahl | `5` | Zulässige Nachrichten pro Minute, mindestens 1. |
| `rate_limit.action` | Auswahl | `warn` | Aktion bei Überschreitung. |
| `spam.enabled` | Boolean | `false` | Direkt wiederholte identische Nachrichten erkennen. |
| `spam.threshold` | Ganzzahl | `3` | Anzahl identischer Nachrichten, mindestens 2. |
| `spam.action` | Auswahl | `mute` | Aktion bei Erkennung. |
| `spam.duration_seconds` | Ganzzahl | `300` | Dauer eines Mutes in Sekunden. |
| `caps.enabled` | Boolean | `false` | Großbuchstabenanteil prüfen; Meldungen mit weniger als fünf Buchstaben werden übersprungen. |
| `caps.threshold_percent` | Ganzzahl | `80` | Grenzwert von 1 bis 100 Prozent. |
| `caps.action` | Auswahl | `warn` | Aktion bei Erkennung. |
| `badwords.enabled` | Boolean | `false` | Reguläre Ausdrücke gegen Nachrichtentext prüfen. |
| `badwords.list` | Textliste | `[]` | Python-RegExp-Muster, ohne Beachtung der Groß-/Kleinschreibung. |
| `badwords.action` | Auswahl | `warn` | Aktion bei Treffer. |
| `warnings.enabled` | Boolean | `true` | Verwarnungen automatisch eskalieren. |
| `warnings.to_kick` | Ganzzahl | `3` | Ab dieser Verwarnungszahl kicken. |
| `warnings.to_ban` | Ganzzahl | `5` | Ab dieser Verwarnungszahl bannen; nicht kleiner als `to_kick`. |

Zulässige Aktionen sind `warn`, `mute`, `kick` und `ban`. `mute` verwendet den
Quiet-Modus `+q`, `ban` setzt `+b` und kickt anschließend. Ob `+q` unterstützt
wird und welche Rechte der Bot braucht, hängt vom IRCd ab.

Kanalwerte überschreiben die globalen Werte rekursiv:

```toml
[moderation.channels."#strict".rate_limit]
enabled = true
messages_per_minute = 3
action = "mute"
```

<a id="plugins"></a>
## `[plugins]`

Dieser Abschnitt gehört zum Core-Lader für externe Erweiterungen. Er wird hier
der Vollständigkeit halber aufgeführt; eingebaute Funktionen gehören unter
`[modules]`.

| Name | Typ | Standard | Beschreibung |
| --- | --- | --- | --- |
| `enabled` | Boolean | `true` | Laden externer Erweiterungen global zulassen. |
| `directory` | Pfad | `plugins` | Verzeichnis relativ zu `config.toml`. |
| `load` | Textliste | `[]` | Explizite Allowlist; Namen dürfen Buchstaben, Ziffern, `_` und `-` enthalten. |
| `settings` | Tabelle | `{}` | Erweiterungsspezifische freie Schlüssel, gruppiert nach Name. |

<a id="environment"></a>
## Umgebungsvariablen

Diese Variablen überschreiben unterstützte TOML-Werte. Bei dateibasiertem Start
müssen die vier Pflichtfelder in `[network]` trotzdem syntaktisch vorhanden
sein, da die Grundstruktur vor den Overrides validiert wird.

| Variable | Konfigurationswert | Hinweis |
| --- | --- | --- |
| `NOVARIUSIRC_PREFIX` | `bot.prefix` | Nichtleerer Text. |
| `NOVARIUSIRC_LANG` | `bot.language` | `de`, `en`, `ja` oder passende Locale-Form. |
| `NOVARIUSIRC_BOT_NAME` | `bot.name` | Stabiler Name für Daten- und Backup-Dateien. |
| `NOVARIUSIRC_SERVER` | `network.server` | Beim ENV-only-Start Pflicht. |
| `NOVARIUSIRC_PORT` | `network.port` | Nur rein numerische Werte werden übernommen. |
| `NOVARIUSIRC_TLS` | `network.tls` | Wahr bei `1`, `true`, `yes` oder `on`; sonst falsch. |
| `NOVARIUSIRC_NICK` | `network.nick` | Beim ENV-only-Start Pflicht. |
| `NOVARIUSIRC_USER` | `network.user` | ENV-only: standardmäßig der Nick. |
| `NOVARIUSIRC_REALNAME` | `network.realname` | ENV-only: standardmäßig der Nick. |
| `NOVARIUSIRC_CHANNELS` | `network.channels` | Kommagetrennte Liste. |
| `NOVARIUSIRC_BIND_IP` | `network.bind_ip` | Lokale Quell-IP. |
| `NOVARIUSIRC_BIND_HOSTNAME` | `network.bind_hostname` | Lokaler Quell-Hostname. |
| `NOVARIUSIRC_SASL_ENABLED` | `auth.sasl_enabled` | Boolean-Syntax wie bei TLS. |
| `NOVARIUSIRC_SASL_MECHANISM` | `auth.sasl_mechanism` | `PLAIN` oder `EXTERNAL`. |
| `NOVARIUSIRC_SASL_USERNAME` | `auth.sasl_username` | SASL-Kontoname. |
| `NOVARIUSIRC_SASL_PASSWORD` | `auth.sasl_password` | Geheimwert. |
| `NOVARIUSIRC_NICKSERV_ENABLED` | `auth.nickserv_enabled` | Boolean-Syntax wie bei TLS. |
| `NOVARIUSIRC_NICKSERV_SERVICE` | `auth.nickserv_service` | Services-Zielname. |
| `NOVARIUSIRC_NICKSERV_USERNAME` | `auth.nickserv_username` | Services-Kontoname. |
| `NOVARIUSIRC_NICKSERV_PASSWORD` | `auth.nickserv_password` | Geheimwert. |
| `NOVARIUSIRC_CERTFP_ENABLED` | `auth.certfp_enabled` | Boolean-Syntax wie bei TLS. |
| `NOVARIUSIRC_CERTFP_CERT_FILE` | `auth.certfp_cert_file` | Zertifikatspfad. |
| `NOVARIUSIRC_CERTFP_KEY_FILE` | `auth.certfp_key_file` | Schlüsselpfad. |
| `NOVARIUSIRC_LOG_ROOT` | `paths.log_root` | Log-Stammverzeichnis. |
| `NOVARIUSIRC_DATA_ROOT` | `paths.data_root` | Daten-Stammverzeichnis. |
| `NOVARIUSIRC_DATABASE_ENABLED` | `database.enabled` | Boolean-Syntax wie bei TLS. |
| `NOVARIUSIRC_DATABASE_BACKEND` | `database.backend` | Registrierter Backendname oder Alias. |
| `NOVARIUSIRC_DATABASE_PATH` | `database.path` | SQLite-Dateipfad. |
| `NOVARIUSIRC_DATABASE_DSN` | `database.dsn` | Verbindungs-DSN einer Serverdatenbank; Geheimwert. |
| `NOVARIUSIRC_OWNER_HOSTMASK` | `owner_bootstrap.hostmask` | Einmalige Owner-Hostmask. |
| `NOVARIUSIRC_OWNER_ACCOUNT` | `owner_bootstrap.account` | Einmaliger Owner-IRC-Kontoname. |
| `NOVARIUSIRC_OWNER_CERTFP` | `owner_bootstrap.certfp` | Einmaliger Owner-CertFP. |

ENV-only benötigt mindestens `NOVARIUSIRC_SERVER` und `NOVARIUSIRC_NICK`:

```console
NOVARIUSIRC_SERVER=irc.example.net \
NOVARIUSIRC_NICK=NovariusBot \
NOVARIUSIRC_TLS=true \
novariusirc --config env
```
