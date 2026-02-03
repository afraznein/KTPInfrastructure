#!/bin/bash
# Deploy ktp-chrt service to existing servers
# Run as root on the target server
#
# Usage: sudo ./deploy-chrt-service.sh
#
# This script creates a systemd timer that applies real-time scheduling
# (chrt -r 20) to all hlds_linux processes every 30 seconds.
# This ensures chrt is reapplied when LinuxGSM restarts crashed servers.

set -e

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root"
    exit 1
fi

echo "Deploying ktp-chrt service..."

# Create the script that applies chrt to game servers
cat > /usr/local/bin/ktp-apply-chrt.sh << 'CHRTSCRIPT'
#!/bin/bash
# KTP Game Server Real-Time Scheduling
# Applies chrt -r 20 to all hlds_linux processes that don't already have it
#
# Run by: ktp-chrt.timer (every 30 seconds)

for pid in $(pgrep -f hlds_linux 2>/dev/null); do
    # Check current scheduling policy
    # chrt -p returns something like "pid X's current scheduling policy: SCHED_OTHER"
    # We want SCHED_RR (round-robin real-time)
    policy=$(chrt -p "$pid" 2>/dev/null | grep -o 'SCHED_[A-Z]*')

    if [ "$policy" != "SCHED_RR" ]; then
        if chrt -r -p 20 "$pid" 2>/dev/null; then
            logger -t ktp-chrt "Applied SCHED_RR priority 20 to hlds_linux PID $pid"
        fi
    fi
done
CHRTSCRIPT
chmod +x /usr/local/bin/ktp-apply-chrt.sh
echo "  -> Created /usr/local/bin/ktp-apply-chrt.sh"

# Create systemd service (oneshot)
cat > /etc/systemd/system/ktp-chrt.service << 'CHRTSVC'
[Unit]
Description=KTP Game Server Real-Time Scheduling
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ktp-apply-chrt.sh
CHRTSVC
echo "  -> Created /etc/systemd/system/ktp-chrt.service"

# Create systemd timer (runs every 30 seconds)
cat > /etc/systemd/system/ktp-chrt.timer << 'CHRTTIMER'
[Unit]
Description=Apply real-time scheduling to KTP game servers

[Timer]
OnBootSec=60
OnUnitActiveSec=30
AccuracySec=5

[Install]
WantedBy=timers.target
CHRTTIMER
echo "  -> Created /etc/systemd/system/ktp-chrt.timer"

# Enable and start the timer
systemctl daemon-reload
systemctl enable ktp-chrt.timer
systemctl start ktp-chrt.timer

echo ""
echo "ktp-chrt service deployed!"
echo ""
echo "Timer status:"
systemctl status ktp-chrt.timer --no-pager
echo ""
echo "To verify it's working:"
echo "  journalctl -t ktp-chrt -f"
echo "  systemctl list-timers | grep ktp-chrt"
