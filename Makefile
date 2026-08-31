.PHONY: help install build clean translations uninstall

PREFIX ?= $(HOME)/NovariusIRC

help:
	@echo "NovariusIRC Build & Install"
	@echo "============================"
	@echo ""
	@echo "Targets:"
	@echo "  make install       - Build und Installation nach $(PREFIX)"
	@echo "  make build         - Nur Wheel-Paket bauen"
	@echo "  make translations  - Gettext-Kataloge kompilieren"
	@echo "  make clean         - Build-Artefakte entfernen"
	@echo "  make uninstall     - Installation entfernen"
	@echo ""
	@echo "Umgebungsvariablen:"
	@echo "  PREFIX=<path>      - Installationspfad (default: ~/NovariusIRC)"

install:
	@NOVARIUSIRC_PREFIX=$(PREFIX) ./install.sh

build:
	python3 scripts/generate_build_info.py
	poetry build; status=$$?; rm -f novariusirc/_build_info.json; exit $$status

translations:
	msgfmt --check-format -o novariusirc/locales/de/LC_MESSAGES/novariusirc.mo novariusirc/locales/de/LC_MESSAGES/novariusirc.po
	msgfmt --check-format -o novariusirc/locales/ja/LC_MESSAGES/novariusirc.mo novariusirc/locales/ja/LC_MESSAGES/novariusirc.po

clean:
	rm -rf dist/ build/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete

uninstall:
	@echo "⚠️  Entferne Installation in $(PREFIX)"
	@read -p "Fortfahren? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -rf "$(PREFIX)/venv" "$(PREFIX)/bin/novariusirc"; \
		echo "✅ Deinstallation abgeschlossen (Instanzen in $(PREFIX)/instances bleiben erhalten)"; \
	fi
