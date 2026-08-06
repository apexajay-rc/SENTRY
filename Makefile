# SENTRY Installation Makefile
# ---------------------------------------------------------

# Paths
PREFIX ?= /opt/sentry
SYSTEMD_DIR ?= /etc/systemd/system
VENV_DIR = $(PREFIX)/venv
PYTHON = python3

.PHONY: all help install uninstall clean

all: help

help:
	@echo "SENTRY - Predictive Linux Resource Orchestration"
	@echo "------------------------------------------------"
	@echo "Usage:"
	@echo "  sudo make install    - Installs SENTRY to $(PREFIX) and configures systemd"
	@echo "  sudo make uninstall  - Removes SENTRY and its systemd service"
	@echo "  make clean           - Cleans local python cache files (__pycache__)"

install:
	@echo "==> Creating installation directories at $(PREFIX)..."
	install -d -m 755 $(PREFIX)
	install -d -m 755 $(PREFIX)/daemon
	install -d -m 755 $(PREFIX)/core
	install -d -m 755 $(PREFIX)/engine
	install -d -m 755 $(PREFIX)/dashboard
	
	@echo "==> Copying source files..."
	cp -r daemon/* $(PREFIX)/daemon/
	cp -r core/* $(PREFIX)/core/
	cp -r engine/* $(PREFIX)/engine/
	cp -r dashboard/* $(PREFIX)/dashboard/
	cp requirements.txt $(PREFIX)/
	# Copy config if it exists, don't fail if it doesn't
	cp sentry_config.yaml $(PREFIX)/ 2>/dev/null || true
	
	@echo "==> Setting up isolated Python Virtual Environment..."
	$(PYTHON) -m venv $(VENV_DIR)
	$(VENV_DIR)/bin/pip install --upgrade pip
	$(VENV_DIR)/bin/pip install -r $(PREFIX)/requirements.txt
	
	@echo "==> Installing systemd service..."
	install -m 644 packaging/sentry.service $(SYSTEMD_DIR)/sentry.service
	systemctl daemon-reload
	
	@echo "================================================="
	@echo "✅ SENTRY Installation Complete!"
	@echo "================================================="
	@echo "To enable and start the daemon, run:"
	@echo "  sudo systemctl enable --now sentry.service"
	@echo ""
	@echo "To view live logs, run:"
	@echo "  journalctl -fu sentry.service"

uninstall:
	@echo "==> Stopping and disabling systemd service..."
	systemctl stop sentry.service 2>/dev/null || true
	systemctl disable sentry.service 2>/dev/null || true
	
	@echo "==> Removing systemd service file..."
	rm -f $(SYSTEMD_DIR)/sentry.service
	systemctl daemon-reload
	
	@echo "==> Removing application files from $(PREFIX)..."
	rm -rf $(PREFIX)
	
	@echo "✅ SENTRY Uninstalled Successfully."

clean:
	@echo "==> Cleaning Python cache files..."
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
