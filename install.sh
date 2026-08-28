#!/usr/bin/env bash
# Installation script für NovariusIRC
# Installiert den Bot in ein separates Verzeichnis (default: ~/NovariusIRC)

set -euo pipefail

# Konfiguration
INSTALL_PREFIX="${NOVARIUSIRC_PREFIX:-$HOME/NovariusIRC}"
VENV_DIR="$INSTALL_PREFIX/venv"
BIN_DIR="$INSTALL_PREFIX/bin"
INSTANCES_DIR="$INSTALL_PREFIX/instances"

echo "🤖 NovariusIRC Installation"
echo "============================"
echo "Install-Prefix: $INSTALL_PREFIX"
echo "Virtual Environment: $VENV_DIR"
echo ""

# Verzeichnisstruktur erstellen
echo "📁 Erstelle Verzeichnisstruktur..."
mkdir -p "$INSTALL_PREFIX"
mkdir -p "$BIN_DIR"
mkdir -p "$INSTANCES_DIR"

# Virtual Environment erstellen (wenn nicht vorhanden)
if [ ! -d "$VENV_DIR" ]; then
    echo "🐍 Erstelle Virtual Environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "♻️  Nutze existierendes Virtual Environment..."
fi

# venv aktivieren
source "$VENV_DIR/bin/activate"

# Poetry Build
echo "📦 Baue Wheel-Paket..."
poetry build -f wheel

# Neueste Wheel-Datei finden
WHEEL=$(ls -t dist/*.whl | head -n1)
echo "📥 Installiere $WHEEL..."

# Installation mit pip im venv
pip install --quiet --upgrade --force-reinstall "$WHEEL"

# Symlink zum Binary erstellen
echo "🔗 Erstelle Binary-Symlink..."
ln -sf "$VENV_DIR/bin/novariusirc" "$BIN_DIR/novariusirc"

# Example-Instanz erstellen (wenn noch nicht vorhanden)
EXAMPLE_INSTANCE="$INSTANCES_DIR/example"
if [ ! -d "$EXAMPLE_INSTANCE" ]; then
    echo "📋 Erstelle Beispiel-Instanz in $EXAMPLE_INSTANCE..."
    mkdir -p "$EXAMPLE_INSTANCE"
    cp config.example.toml "$EXAMPLE_INSTANCE/config.toml"
    cp secrets.example.toml "$EXAMPLE_INSTANCE/secrets.toml"
    cp -r config/ "$EXAMPLE_INSTANCE/" 2>/dev/null || true
    cp -r plugins/ "$EXAMPLE_INSTANCE/" 2>/dev/null || true
fi

# README in instances/ erstellen
cat > "$INSTANCES_DIR/README.md" << 'EOF'
# NovariusIRC Instanzen

Jedes Unterverzeichnis hier ist eine separate Bot-Instanz.

## Neue Instanz erstellen

```bash
cd ~/NovariusIRC/instances
mkdir mein-bot
cd mein-bot
cp ../example/config.toml .
cp ../example/secrets.toml .
# Config anpassen...
```

## Bot starten

```bash
~/NovariusIRC/bin/novariusirc instances/mein-bot/config.toml
```

Oder mit relativem Pfad aus dem Instanz-Verzeichnis:
```bash
cd ~/NovariusIRC/instances/mein-bot
../../bin/novariusirc config.toml
```
EOF

echo ""
echo "✅ Installation abgeschlossen!"
echo ""
echo "📍 Installation: $INSTALL_PREFIX"
echo "🐍 Virtual Environment: $VENV_DIR"
echo "🔧 Binary: $BIN_DIR/novariusirc"
echo "🤖 Instanzen: $INSTANCES_DIR"
echo ""
echo "💡 Füge zu deiner Shell-Config hinzu:"
echo "   export PATH=\"$BIN_DIR:\$PATH\""
echo ""
echo "🚀 Bot starten (Beispiel):"
echo "   novariusirc $INSTANCES_DIR/example/config.toml"
echo ""
echo "🔍 Oder aktiviere das venv direkt:"
echo "   source $VENV_DIR/bin/activate"
