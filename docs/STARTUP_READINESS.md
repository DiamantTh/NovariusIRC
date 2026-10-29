# Betriebsstand und nächste Entwicklungsstufen

Stand: 29. Oktober 2026. Diese Einschätzung beschreibt den aktuellen Quellcode;
ein erfolgreicher Verbindungstest oder ein Release wird dadurch nicht behauptet.
Die ausführliche Funktionsübersicht steht in [FEATURES.md](FEATURES.md).

## Im Source vorhanden

| Bereich | Stand im Code |
| --- | --- |
| IRC-Core | Async-Verbindung, TLS, Reconnect, IRCv3 CAP, SASL PLAIN/EXTERNAL, Protokollzustand, begrenzte Queues und CTCP PING/VERSION/CLIENTINFO |
| Konfiguration | Strikte TOML-Konfiguration, Includes, ENV-Overrides, ENV-only-Start und Prüf-/Statusbefehle |
| Befehle und Rollen | Gemeinsame Registry, Kollisionsschutz, Kanaladressierung, Rollen via Hostmask/Account/CertFP und DB-Verwaltung |
| Lokale Steuerung | CLI, Terminal-Konsole, Unix-Control-Socket und optionale Read-only-Tornado-API |
| Datenbanken | SQLAlchemy-Backends für SQLite, PostgreSQL, MariaDB, MySQL und MSSQL; serverseitige Treiber/DSNs erforderlich |
| Migrationen | Gepackte Alembic-Revisionen und explizite Init-/Check-/Upgrade-Befehle; SQLite-Upgrade arbeitet über geprüfte Kopien |
| Backups | Manueller, verifizierter SQLite-/Daten-Export und Offline-Restore; optional bzip3 |
| RSS/Atom | Eingebautes optionales Modul, Feed-Caching, Limits, Vorlagen und persistenter Zustand |
| Moderation | Core-Dienst mit Rate-/Spam-/Caps-/Wort-/URL-Prüfung, Warnungen, Aktionen, DB-Regeln, Overrides und Evidence-Metadaten |
| Plugins | Explizite Allowlist, Paketmetadaten, Hook-/Command-API und optionale Worker-Prozesse mit begrenztem IPC |
| Logging | Strukturierte Ausgabe, tägliche Core-Logs mit Größenrotation sowie getrennte IRC-, Raw- und Moderationslogs |
| Sprachen | Englisch, Deutsch und Japanisch für Core- und Modulmeldungen |
| Build-Info | CLI-Version, IRC-Version, CTCP VERSION und erweitertes botinfo |

Die Supportmatrix und Implementierungsgrenzen stehen in
[IRC_PROTOCOL.md](IRC_PROTOCOL.md), [PLUGINS.md](PLUGINS.md) und
[FEATURES.md](FEATURES.md).

## Für einen belastbaren Produktivbetrieb noch zu prüfen

- Längere reale Verbindungstests gegen moderne und klassische IRC-Netze,
  einschließlich SASL/Services, Reconnect und tatsächlicher Channel-Rechte.
- Wiederherstellung aus einem extern gelagerten Backup praktisch durchführen.
- Server-Datenbank-Backends jeweils mit echten Instanzen und ihren Treibern
  testen; der Codepfad ist vorhanden, aber diese Dokumentation behauptet keine
  produktive Validierung jeder Servervariante.
- Für den jeweiligen Host passende TLS-Vertrauensketten und Log-/Daten-
  Speicherorte konfigurieren.
- Veröffentlichung von Container- und Python-Paketen benötigt aktive
  Forgejo-Registry-Anmeldedaten. Lokale Builds sind keine Veröffentlichung.

## Noch nicht implementiert oder bewusst nicht angeboten

- Automatische Erkennung und RDAP/WHOIS-Abfrage von geposteten IP-Adressen,
  Domains, Anschriften oder Telefonnummern.
- Weboberfläche und schreibende HTTP-API.
- Vollständige OS-Sandbox für Plugin-Worker.
- Implementierung semantischer IRCv3-Draft-Funktionen allein durch deren
  Aushandlung.

## Startablauf

1. Instanzkonfiguration und gewünschte Includes erstellen.
2. novariusirc config check --config ./config ausführen.
3. Bei aktivierter Datenbank explizit initialisieren und prüfen:

   ~~~console
   novariusirc database init --config ./config
   novariusirc database check --config ./config
   ~~~

4. Bot starten und Verbindung, Rollen sowie Kanalrechte kontrollieren.
5. Backups regelmäßig erstellen und außerhalb des Instanzdatenträgers ablegen.
