#!/usr/bin/env bash
# Installation script für NovariusIRC
# Installiert den Bot in ein separates Verzeichnis (default: ~/NovariusIRC)

set -euo pipefail

PYTHON_BIN=""
for candidate in python3.14 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && \
        "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)'; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "NovariusIRC requires Python 3.14 or newer (python3.14 or python3)." >&2
    exit 1
fi

# Konfiguration
INSTALL_PREFIX="${NOVARIUSIRC_INSTALL_PREFIX:-$HOME/NovariusIRC}"
VENV_DIR="$INSTALL_PREFIX/venv"
INSTANCES_DIR="$INSTALL_PREFIX/instances"

echo "🤖 NovariusIRC Installation"
echo "============================"
echo "Install-Prefix: $INSTALL_PREFIX"
echo "Virtual Environment: $VENV_DIR"
echo ""

# Verzeichnisstruktur erstellen
echo "📁 Erstelle Verzeichnisstruktur..."
mkdir -p "$INSTALL_PREFIX"
mkdir -p "$INSTANCES_DIR"

# Virtual Environment erstellen (wenn nicht vorhanden)
if [ ! -d "$VENV_DIR" ]; then
    echo "🐍 Erstelle Virtual Environment..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "♻️  Nutze existierendes Virtual Environment..."
fi

if ! "$VENV_DIR/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)'; then
    echo "The existing virtual environment at $VENV_DIR uses Python older than 3.14." >&2
    echo "Recreate that environment with Python 3.14+ before installing; it was left untouched." >&2
    exit 1
fi

# Build in a disposable staging directory. Installation must never leave wheel,
# metadata, or generated build information in the source checkout.
echo "📦 Baue Wheel-Paket..."
SOURCE_DIR="$(pwd)"
BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/novariusirc-build.XXXXXX")"
BUILD_SOURCE="$BUILD_DIR/source"
trap 'rm -rf "$BUILD_DIR"' EXIT
mkdir -p "$BUILD_SOURCE"
tar \
    --exclude-vcs \
    --exclude='./.venv' \
    --exclude='./dist' \
    --exclude='./build' \
    --exclude='./*.egg-info' \
    -cf - -C "$SOURCE_DIR" . | tar -xf - -C "$BUILD_SOURCE"
(
    cd "$BUILD_SOURCE"
    "$PYTHON_BIN" scripts/generate_build_info.py
    poetry build -f wheel
)

# Neueste Wheel-Datei finden
WHEEL=$(ls -t "$BUILD_SOURCE"/dist/*.whl | head -n1)
echo "📥 Installiere $WHEEL..."

# Installation mit pip im venv
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet --upgrade --force-reinstall "$WHEEL"

# Example-Instanz erstellen (wenn noch nicht vorhanden)
EXAMPLE_INSTANCE="$INSTANCES_DIR/example"
if [ ! -d "$EXAMPLE_INSTANCE" ]; then
    echo "📋 Erstelle Beispiel-Instanz in $EXAMPLE_INSTANCE..."
    mkdir -p "$EXAMPLE_INSTANCE/config"
    cp config/config.example.toml "$EXAMPLE_INSTANCE/config/config.toml"
    cp config/secrets.example.toml "$EXAMPLE_INSTANCE/config/secrets.toml"
    cp config/feeds.example.toml "$EXAMPLE_INSTANCE/config/feeds.toml"
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
cp -a ../example/config .
# Config anpassen...
```

## Bot starten

```bash
~/NovariusIRC/venv/bin/novariusirc --instance mein-bot
```

Oder mit relativem Pfad aus dem Instanz-Verzeichnis:
```bash
cd ~/NovariusIRC/instances/mein-bot
../../venv/bin/novariusirc --instancedir .
```
EOF

echo ""
echo "✅ Installation abgeschlossen!"
echo ""
echo "📍 Installation: $INSTALL_PREFIX"
echo "🐍 Virtual Environment: $VENV_DIR"
echo "🔧 Binary: $VENV_DIR/bin/novariusirc"
echo "🤖 Instanzen: $INSTANCES_DIR"
echo ""
echo "🚀 Bot starten (Beispiel):"
echo "   $VENV_DIR/bin/novariusirc --instance example"
echo ""
echo "🔍 Oder aktiviere das venv direkt:"
echo "   source $VENV_DIR/bin/activate"
