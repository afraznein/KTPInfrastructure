#!/bin/bash
# Install the hltv-demo-renamer service on the data server.
# Run as root on 74.91.112.242.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Installing from $SCRIPT_DIR"

# 1. Service script
install -m 755 "$SCRIPT_DIR/hltv-demo-renamer.py" /usr/local/bin/hltv-demo-renamer.py

# 2. systemd unit
install -m 644 "$SCRIPT_DIR/hltv-demo-renamer.service" /etc/systemd/system/hltv-demo-renamer.service

# 3. Cleanup script + cron
install -m 755 "$SCRIPT_DIR/ktp-demo-cleanup-auto.sh"  /usr/local/bin/ktp-demo-cleanup-auto.sh
install -m 644 "$SCRIPT_DIR/ktp-demo-cleanup-auto.cron" /etc/cron.d/ktp-demo-cleanup-auto

# 4. State + log dirs
mkdir -p /var/lib/hltv-demo-renamer
touch /var/log/ktp-demo-cleanup-auto.log

# 5. Ensure paramiko is installed
if ! python3 -c 'import paramiko' 2>/dev/null; then
    echo "Installing python3-paramiko..."
    apt-get update -qq
    apt-get install -y python3-paramiko
fi

# 6. Reload systemd
systemctl daemon-reload

cat <<'EOF'

================================================================
Install complete.

To enable + start the renamer service:
    systemctl enable --now hltv-demo-renamer

To run a one-shot dry-run for verification:
    /usr/local/bin/hltv-demo-renamer.py --dry-run

Logs:
    journalctl -u hltv-demo-renamer -f
    tail -f /var/log/ktp-demo-cleanup-auto.log

NOTE: Does nothing useful until KTPHLTVRecorder v1.7.0 is active
fleet-wide AND HLTV cfgs include `record auto_<friendly>`.
================================================================
EOF
