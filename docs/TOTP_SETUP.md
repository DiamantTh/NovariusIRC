# Optionaler TOTP-Baustein

NovariusIRC enthält TOTP-Prüfung und zeitlich begrenzte Sitzungen nach RFC 6238
als optionalen Baustein für Owner- und Admin-Rechte. TOTP ist weder für den
normalen Botstart noch für die lokale Unix-Control-Shell erforderlich.

Ein IRC-Command wie `!auth` und eine CTCP-Anmeldung sind derzeit **nicht**
implementiert. Die Konfiguration und diese Hinweise dienen der Vorbereitung;
der konkrete Bedienweg wird erst festgelegt, wenn klar ist, ob TOTP überhaupt
und an welcher Stelle eingesetzt werden soll.

## Konfigurierbare Parameter

### Hash-Algorithmus (`totp_digest`)
- **`sha1`**: Legacy, kompatibel mit allen Authenticator-Apps
- **`sha256`** (Standard): Moderne Alternative für neue Setups
- **`sha512`**: Höchste Sicherheit, erfordert App-Support

### Code-Länge (`totp_digits`)
- **`6`**: 6-stelliger Code (z.B. `123456`)
- **`8`** (Standard): 8-stelliger Code (z.B. `12345678`) - höhere Sicherheit

### Zeitfenster (`totp_interval`)
- **`30`** (Standard): 30 Sekunden Gültigkeit pro Code
- `60`: 60 Sekunden (seltener verwendet)

### Toleranz-Fenster (`totp_valid_window`)
- **`4`** (Standard): ±4 Intervalle (bei 30s → ±120s Toleranz)
- Kleinere Werte begrenzen die Toleranz für Uhren-Drift stärker.

## AEGIS Authenticator Setup

AEGIS unterstützt alle modernen TOTP-Parameter. Empfohlene Konfiguration:

```toml
[auth]
totp_digest = "sha256"       # SHA-256 statt veraltetes SHA-1
totp_digits = 8              # 8 Stellen für höhere Sicherheit
totp_interval = 30           # Standard 30 Sekunden
totp_valid_window = 1        # ±30s Toleranz
```

### AEGIS Import

1. **Manueller Import** (empfohlen für SHA-256/SHA-512):
   - In AEGIS: "+" → "Enter details"
   - Type: **Time-based**
   - Algorithm: **SHA-256** (oder SHA-512)
   - Digits: **8**
   - Period: **30**
   - Secret: Dein BASE32-Secret

2. **QR-Code** (für SHA-1 kompatibel):
   ```python
   import pyotp

   secret = "JBSWY3DPEHPK3PXP"
   totp = pyotp.TOTP(secret, digits=6, digest="sha1")
   print(totp.provisioning_uri("NovariusIRC", issuer_name="IRC Bot"))
   ```

## Secret-Generierung

```python
import pyotp
import base64
import os

# Generiere kryptographisch sicheres Secret
random_bytes = os.urandom(32)  # 256 Bit
secret = base64.b32encode(random_bytes).decode("utf-8").strip("=")
print(f"TOTP Secret: {secret}")
```

Oder via CLI:
```bash
python3 -c "import pyotp; print(pyotp.random_base32())"
```

## Sicherheitsempfehlungen

### Für Produktiv-Systeme
```toml
[auth]
totp_digest = "sha512"       # Stärkster Hash
totp_digits = 8              # 8-stellige Codes
totp_valid_window = 1        # Knappe Toleranz
session_timeout_seconds = 900 # 15 Minuten Session
```

### Für Kompatibilität (alle Authenticator-Apps)
```toml
[auth]
totp_digest = "sha1"         # Universal kompatibel
totp_digits = 6              # Standard-Länge
totp_valid_window = 1        # Ausreichende Toleranz
```

## Individuelle Secrets pro User

```toml
[roles]
owners = [
    { 
        hostmask = "alice!*@*.trusted.net", 
        require_totp = true, 
        totp_secret = "JBSWY3DPEHPK3PXP"  # Alices eigenes Secret
    },
    { 
        hostmask = "bob!~user@host.tld", 
        require_totp = true, 
        totp_secret = "KRSXG5CTMVRXEZLU"  # Bobs eigenes Secret
    }
]
```

## Bedienweg ist noch offen

Es gibt derzeit absichtlich keinen nutzbaren IRC- oder CTCP-Login-Befehl. Vor
einer Integration muss entschieden werden, ob TOTP für IRC-Commands, eine
spätere SSH-Control-Shell oder gar nicht verwendet werden soll. Bis dahin
sollte `require_totp = true` nicht in einer produktiven Rollenregel gesetzt
werden, weil diese Rolle ohne Login-Flow nicht aktiviert werden kann.

## Troubleshooting

### Spätere Fehlersuche bei einer Integration
- Uhrzeit-Synchronisation (NTP) prüfen.
- TOTP-Parameter (Digest, Digits, Interval) in App und Konfiguration abgleichen.
- `totp_valid_window` nur bewusst für Uhren-Drift erhöhen.
- Hostmask-Match (`/whois dein_nick`) prüfen, falls Hostmask-Rollen verwendet werden.

### AEGIS zeigt falschen Code
- Algorithm in AEGIS muss mit `totp_digest` übereinstimmen
- Digits in AEGIS muss mit `totp_digits` übereinstimmen
- Period in AEGIS muss mit `totp_interval` übereinstimmen

### Keine aktive Sitzung

Derzeit erwartbar: Ohne implementierten Login-Flow kann keine TOTP-Sitzung über
IRC erzeugt werden.
