# Funktionsübersicht

**Sprachen:** Deutsch · [English](FEATURES.en.md)

Diese Übersicht beschreibt den Code im aktuellen Quellstand. Optionale
Funktionen sind nicht zwangsläufig in einer Standardinstanz aktiviert. Die
Konfigurationsreferenz erklärt Schalter und Einstellungen; Protokoll-, Plugin-
und Betriebsdokumentation beschreiben Verhalten und Grenzen.

## IRC-Protokoll und Verbindung

- Ein IRC-Netz pro Prozess; mehrere Netze werden mit getrennten Instanzen
  betrieben.
- Asynchroner Verbindungsablauf mit TLS, Reconnect-Backoff, Zeitlimits,
  sauberem Shutdown, begrenzten Eingabezeilen und ausgangsseitiger
  Sendebegrenzung.
- IRCv3-CAP-302-Aushandlung, Prüfung angebotener Capabilities, dynamisches
  CAP NEW/DEL, Message-Tags, Batches, Serverzeit und strukturierte Standard-
  Replies.
- SASL PLAIN und EXTERNAL, TLS-Clientzertifikate sowie NickServ-Identifizierung.
- ISUPPORT-gestützte Casemapping-, Kanal-, Benutzer-, Präfix-, Modus- und
  WHO/WHOX-Verarbeitung.
- IRCv3 ist für den normalen IRC-Betrieb optional. Account-Tags, Away-Status
  und weitere Erweiterungsdaten werden nur verwendet, wenn der Server sie
  bereitstellt.
- CTCP PING, VERSION und CLIENTINFO. VERSION meldet die Paketidentität.

Details: [IRC-Protokollunterstützung](IRC_PROTOCOL.md).

## Bot-Befehle, Identitäten und Rechte

- Gemeinsame, nicht zwischen Groß- und Kleinschreibung unterscheidende
  Befehlsregistry für Core, eingebaute Module und externe Plugins. Doppelte
  Namen und Aliase werden abgelehnt.
- Query-Befehle nutzen den konfigurierten Präfix. Im Kanal muss zuerst der
  Botnick angesprochen werden; danach ist der Präfix optional.
- Eingebaute Befehle: help, ping, uptime, version, status und botinfo.
- Rollen user, admin und owner. Identitäten können per Hostmask,
  IRCv3-Account-Tag oder CertFP gebunden werden. DB-Bindungen verwaltet der
  Owner mit dem Befehl role.
- Optionale Testmeldungen nach erfolgreicher Registrierung werden nur an
  explizit angegebene Nicks gesendet. Die Meldung enthält keine Geheimnisse.

## Konfiguration und Übersetzungen

- Strikte TOML-Konfiguration, Includes mit relativen oder absoluten Pfaden,
  ENV-Overrides, Validierung und Config-Status ohne IRC-Verbindung.
- Englische, deutsche und japanische Übersetzungskataloge. Fehlt eine
  Spracheinstellung, wird die Umgebung ausgewertet.
- Start ausschließlich über Environment-Variablen für passende Container-
  Setups.

Details: [Konfiguration (DE)](CONFIGURATION.md) ·
[Konfiguration (EN)](CONFIGURATION.en.md).

## Persistenz, Backups und Monitoring

- SQLAlchemy-Core-Backends für SQLite, PostgreSQL, MariaDB, MySQL und Microsoft
  SQL Server. Serverdatenbanken benötigen Treiber und DSN.
- Explizite Datenbankbefehle für Init, Check und Upgrade. SQLite nutzt WAL,
  vollständige Synchronisierung, Foreign Keys und Integritätsprüfungen.
- Rollen- und Feedzustand werden persistent gespeichert. Moderation nutzt
  standardmäßig eine eigene SQLite-Datei oder separate Tabellen im
  konfigurierten SQL-Backend.
- Geprüfte Offline-Backups für SQLite und Zusatzdateien mit SHA-256-Manifest,
  optionaler bzip3-Kompression und expliziter Wiederherstellung.
- Read-only-Tornado-Monitoring-API mit Health, Readiness und versionierten
  Statusdaten; optionale Prozessmetriken über psutil. Keine Schreib-API und
  kein Webpanel.
- CLI, Terminalkonsole und lokaler Unix-Control-Socket. Der Socket nutzt
  Dateisystemrechte und öffnet keinen TCP-Control-Port.

Details: [Betrieb](OPERATIONS.md) ·
[Datenbank- und API-Konfiguration](CONFIGURATION.md).

## Eingebautes RSS-/Atom-Modul

- Optionales rss_announcer-Modul mit begrenztem Polling, HTTP-Antwortgröße,
  Zeitlimit, TLS- und User-Agent-Einstellungen.
- ETag-/Last-Modified-Behandlung, persistenter Status gelesener Feed-Einträge,
  Intervalle pro Feed und Kanal, Vorlagen und Meldungsgrenzen.
- feed-Befehl zum Auflisten und begrenzten manuellen Abrufen.

Details: [Feed-Konfiguration](CONFIGURATION.md#feeds) ·
[Beispiel](../config/feeds.example.toml).

## Moderations-Core

- Core-Dienst mit einzeln konfigurierbarer Nachrichtenrate, Wiederholungs-,
  Caps-, Wort- und URL-Prüfung.
- Allow-/Block-Regeln aus Konfiguration, nachladbaren Dateien und Datenbank.
  Laufzeiteinstellungen können je Kanal überschrieben werden.
- Verwarnungseskalation, Kick/Ban/Mute-Aktionen, konfigurierbare Zielmasken,
  Entscheidungslogs und persistente Maßnahmen-/Evidence-Metadaten.
- Automatische Erkennung von Anschriften oder Telefonnummern sowie
  RDAP-/WHOIS-Abfragen sind derzeit nicht implementiert.

Details: [Moderationskonfiguration](CONFIGURATION.md#moderation) ·
[Beispiel](../config/moderation.example.toml).

## Externe Plugin-Worker

- Externe Plugins werden nur über eine explizite Allowlist geladen.
  Paketplugins definieren Metadaten, Abhängigkeiten, Befehle und Hooks.
- Optionale Kindprozesse nutzen begrenztes JSON-IPC, Payload- und Antwortlimits,
  Zeitlimits, Rechteprüfung im Core, Plugin-Datenordner und Beendigung bei
  Fehlern oder Entladen.
- Ein Kindprozess ist keine Betriebssystem-Sandbox. Ohne zusätzliche
  Isolation hat er weiterhin die Datei- und Netzwerkrechte des Botbenutzers.

Details: [Plugin-Dokumentation](PLUGINS.md).

## Logs und Buildinformationen

- Strukturierte Ausgabe auf stdout und rotierende, datumsbasierte Core-Logs.
  Kanal-, Query-, Raw-Protokoll- und Moderationslogs sind getrennte Ausgaben.
- Optionale journald-Ausgabe und konfigurierbare Ziele.
- -v, -V und --version zeigen Paket-, Build- und Laufzeitdetails. Der
  IRC-Befehl botinfo zeigt erweiterte Diagnoseinformationen.

Siehe [Betrieb](OPERATIONS.md) und [Protokoll](IRC_PROTOCOL.md).

## Bewusste Grenzen

- Kein Webpanel, keine schreibende HTTP-API und kein öffentlicher
  API-Authentifizierungsablauf.
- IRC-Moderation benötigt entsprechende Kanalrechte und unterstützte Server-
  Modi.
- Plugin-Worker bieten Prozessisolierung, aber keine vollständige
  Betriebssystem-Sandbox.
- Das Anfordern einer IRCv3-Draft-Capability bedeutet nicht, dass deren
  übergeordnete Semantik implementiert ist.

Betriebsstatus und verbleibende Arbeiten stehen in der
[Startbereitschaft](STARTUP_READINESS.md).
