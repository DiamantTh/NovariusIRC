#!/usr/bin/env bash
# Installation script für NovariusIRC
# Installiert den Bot in ein separates Verzeichnis (default: ~/NovariusIRC)

set -euo pipefail

# Konfiguration
INSTALL_PREFIX="${NOVARIUSIRC_PREFIX:-$HOME/NovariusIRC}"
PYTHON_VERSION=$(python3 --version | awk '{print $2}' | cut -d. -f1,2)
LIB_DIR="$INSTALL_PREFIX/lib/python$PYTHON_VERSION/site-packages"
BIN_DIR="$INSTALL_PREFIX/bin"
INSTANCES_DIR="$INSTALL_PREFIX/instances"

echo "🤖 NovariusIRC Installation"
echo "============================"
echo "Install-Prefix: $INSTALL_PREFIX"
echo "Python Version: $PYTHON_VERSION"
echo ""

# Verzeichnisstruktur erstellen
echo "📁 Erstelle Verzeichnisstruktur..."
mkdir -p "$LIB_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$INSTANCES_DIR"

# Poetry Build
echo "📦 Baue Wheel-Paket..."
poetry build -f wheel

# Neueste Wheel-Datei finden
WHEEL=$(ls -t dist/*.whl | head -n1)
echo "📥 Installiere $WHEEL..."

# Installation mit pip
pip install --quiet --upgrade --force-reinstall \
    --target="$LIB_DIR" \
    "$WHEEL"

# Binary-Wrapper erstellen (damit PYTHONPATH korrekt gesetzt ist)
echo "🔗 Erstelle Binary-Wrapper..."
cat > "$BIN_DIR/novariusirc" << EOF
#!/usr/bin/env bash
# NovariusIRC Launcher
export PYTHONPATH="$LIB_DIR:\$PYTHONPATH"
exec python3 -m novariusirc "\$@"
EOF
chmod +x "$BIN_DIR/novariusirc"

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
echo "🔧 Binary: $BIN_DIR/novariusirc"
echo "🤖 Instanzen: $INSTANCES_DIR"
echo ""
echo "💡 Füge zu deiner Shell-Config hinzu:"
echo "   export PATH=\"$BIN_DIR:\$PATH\""
echo ""
echo "🚀 Bot starten (Beispiel):"
echo "   novariusirc $INSTANCES_DIR/example/config.toml"
