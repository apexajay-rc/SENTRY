#!/bin/bash

echo "[SENTRY INSTALLER] Compiling release build..."
cargo build --release

echo "[SENTRY INSTALLER] Moving binary to /usr/local/bin..."
sudo cp target/release/sentry-core /usr/local/bin/sentry-core

# Dynamically figure out the real human user, even if they used 'sudo'
ACTUAL_USER=${SUDO_USER:-$USER}
echo "[SENTRY INSTALLER] Configuring Audio Monitor for user: $ACTUAL_USER"

echo "[SENTRY INSTALLER] Generating systemd service file..."
# Generate the service file on the fly with the correct user
cat <<EOF | sudo tee /etc/systemd/system/sentry.service > /dev/null
[Unit]
Description=SENTRY Ring -1 CPU Scheduler Daemon
After=network.target bpf.mount

[Service]
Type=simple
ExecStart=/usr/local/bin/sentry-core
Environment="SUDO_USER=$ACTUAL_USER"
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "[SENTRY INSTALLER] Enabling and starting SENTRY daemon..."
sudo systemctl daemon-reload
sudo systemctl enable sentry
sudo systemctl restart sentry

echo "SENTRY has been successfully installed"
echo "To view live logs, run: journalctl -u sentry -f"
