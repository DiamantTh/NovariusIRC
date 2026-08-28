# TOTP Authentication Setup

NovariusIRC unterstützt TOTP (Time-based One-Time Password) nach RFC 6238 für Owner- und Admin-Authentifizierung.

## Konfigurierbare Parameter

### Hash-Algorithmus (`totp_digest`)
- **`sha1`** (Standard): Legacy, kompatibel mit allen Authenticator-Apps
- **`sha256`**: Moderne Alternative, empfohlen für neue Setups
- **`sha512`**: Höchste Sicherheit, erfordert App-Support

### Code-Länge (`totp_digits`)
- **`6`** (Standard): 6-stelliger Code (z.B. `123456`)
- **`8`**: 8-stelliger Code (z.B. `12345678`) - höhere Sicherheit

### Zeitfenster (`totp_interval`)
- **`30`** (Standard): 30 Sekunden Gültigkeit pro Code
- `60`: 60 Sekunden (seltener verwendet)

### Toleranz-Fenster (`totp_valid_window`)
- **`1`** (Standard): ±1 Intervall (bei 30s → ±30s Toleranz)
- `2`: ±2 Intervalle (bei 30s → ±60s Toleranz) - für Uhren-Drift

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

## Authentifizierung

### Via Private Message
```
/msg NovariusBot !auth 123456
```

### Via CTCP (weniger sichtbar in Logs)
```
/ctcp NovariusBot AUTH 123456
```

## Troubleshooting

### "Authentication failed"
- Prüfe Uhrzeit-Synchronisation (NTP)
- Prüfe TOTP-Parameter (Digest, Digits, Interval) in App
- Erhöhe `totp_valid_window` für Uhren-Drift
- Prüfe Hostmask-Match (`/whois dein_nick`)

### AEGIS zeigt falschen Code
- Algorithm in AEGIS muss mit `totp_digest` übereinstimmen
- Digits in AEGIS muss mit `totp_digits` übereinstimmen
- Period in AEGIS muss mit `totp_interval` übereinstimmen

### "No active authentication session"
- Session ist abgelaufen (`session_timeout_seconds`)
- Erneut authentifizieren mit `!auth` oder CTCP
