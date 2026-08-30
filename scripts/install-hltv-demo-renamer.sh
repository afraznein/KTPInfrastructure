#!/bin/bash
# Install the hltv-demo-renamer service on the data server.
# Run as root on <DATA_SERVER_IP>.

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

# 3b. Guard verifier. Installing the files does not establish that the guards are
# in effect -- see the header of the script for why that distinction cost us two
# days of match demos.
install -m 755 "$SCRIPT_DIR/verify-hltv-demo-renamer.sh" /usr/local/bin/verify-hltv-demo-renamer.sh

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

To run a one-shot dry-run of the renamer itself:
    /usr/local/bin/hltv-demo-renamer.py --dry-run

To verify the WEDGE GUARDS are live (read-only; run after any upgrade):
    /usr/local/bin/verify-hltv-demo-renamer.sh
  Checks Type=notify/WatchdogSec are in effect, that the poll loop is both
  ticking AND reading every game host, and that the cleanup interlock will
  refuse to delete when it is not. Exits non-zero on any failure.

Logs:
    journalctl -u hltv-demo-renamer -f
    tail -f /var/log/ktp-demo-cleanup-auto.log

NOTE: Does nothing useful until KTPHLTVRecorder v1.7.0 is active
fleet-wide AND HLTV cfgs include `record auto_<friendly>`.
================================================================
EOF
