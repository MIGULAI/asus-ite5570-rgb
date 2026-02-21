#!/usr/bin/env bash
# install.sh — install ITE5570 lighting daemon on Fedora
# Run as root: sudo bash install.sh

set -e  # stop on any error

echo "=== ITE5570 Lighting Daemon — Install ==="

# ── 1. Copy daemon script ──────────────────────────────────────────────────────
echo "[1/5] Installing daemon script → /usr/local/lib/ite5570/"
mkdir -p /usr/local/lib/ite5570
cp ite5570_daemon.py /usr/local/lib/ite5570/ite5570_daemon.py
chmod 755 /usr/local/lib/ite5570/ite5570_daemon.py

# ── 2. Install config file ─────────────────────────────────────────────────────
echo "[2/5] Installing config → /etc/ite5570/config.json"
mkdir -p /etc/ite5570
if [ -f /etc/ite5570/config.json ]; then
    echo "  config.json already exists — skipping (not overwriting your settings)"
else
    cp config.json /etc/ite5570/config.json
    chmod 644 /etc/ite5570/config.json
fi

# ── 3. Install systemd unit ────────────────────────────────────────────────────
echo "[3/5] Installing systemd unit → /etc/systemd/system/ite5570.service"
cp ite5570.service /etc/systemd/system/ite5570.service
chmod 644 /etc/systemd/system/ite5570.service

# ── 4. Reload systemd and enable the service ──────────────────────────────────
echo "[4/5] Enabling service"
systemctl daemon-reload
systemctl enable ite5570.service

# ── 5. Start the service now ───────────────────────────────────────────────────
echo "[5/5] Starting service"
systemctl start ite5570.service

echo ""
echo "=== Done ==="
echo ""
echo "Useful commands:"
echo "  systemctl status ite5570          # check if running"
echo "  journalctl -u ite5570 -f          # live logs"
echo "  nano /etc/ite5570/config.json     # edit color/mode"
echo "  systemctl reload ite5570          # apply config without restart"
echo "  systemctl restart ite5570         # full restart"
echo "  systemctl stop ite5570            # stop + release LEDs to firmware"
echo "  systemctl disable ite5570         # don't start on boot"
