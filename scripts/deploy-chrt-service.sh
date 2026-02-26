#!/bin/bash
# Deploy ktp-chrt service to existing servers
# Run as root on the target server
#
# Usage: sudo ./deploy-chrt-service.sh [--chicago]
#
# This script creates a systemd timer that applies CPU pinning + SCHED_FIFO
# scheduling to all hlds_linux processes every 30 seconds.
# This ensures pinning is reapplied when LinuxGSM restarts crashed servers.
#
# Options:
#   --chicago   Use 4-vCPU layout (3 dedicated + 2 shared on vCPU 0)
#               Default is 8-CPU baremetal layout (5 dedicated CPUs)

set -e

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root"
    exit 1
fi

# Parse arguments
CHICAGO=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --chicago) CHICAGO=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "Deploying ktp-chrt service..."

if [ "$CHICAGO" = true ]; then
    echo "  Using Chicago 4-vCPU layout"
    CPU_MAP='declare -A PORT_CPU_MAP=([27015]=1 [27016]=2 [27017]=3 [27018]=0 [27019]=0)'
    COMMENT='# vCPU layout: 0=sys+27018+27019, 1=27015, 2=27016, 3=27017'
else
    echo "  Using baremetal 8-CPU layout"
    CPU_MAP='declare -A PORT_CPU_MAP=([27015]=2 [27016]=3 [27017]=5 [27018]=6 [27019]=7)'
    COMMENT='# CPU layout: 0,1,4=sys, 2=27015, 3=27016, 5=27017, 6=27018, 7=27019'
fi

# Create the script that applies CPU pinning + SCHED_FIFO to game servers
cat > /usr/local/bin/ktp-apply-chrt.sh << CHRTSCRIPT
#!/bin/bash
# KTP Game Server CPU Pinning + Real-Time Scheduling
# Run by: ktp-chrt.timer (every 30 seconds)
$COMMENT
$CPU_MAP

for pid in \$(pgrep -f hlds_linux 2>/dev/null); do
    port=\$(tr '\\0' ' ' < /proc/\$pid/cmdline 2>/dev/null | grep -oP '(?<=-port )\\d+')
    [ -z "\$port" ] && port=\$(ps -p "\$pid" -o args= 2>/dev/null | grep -oP '(?<=-port )\\d+')
    [ -z "\$port" ] && continue

    target_cpu=\${PORT_CPU_MAP[\$port]}
    [ -z "\$target_cpu" ] && continue

    # Pin to designated CPU
    current=\$(taskset -cp "\$pid" 2>/dev/null | grep -oP '(?<=: ).*')
    [ "\$current" != "\$target_cpu" ] && taskset -cp "\$target_cpu" "\$pid" 2>/dev/null && \\
        logger -t ktp-chrt "Pinned port \$port PID \$pid to CPU \$target_cpu"

    # Apply SCHED_FIFO priority 50
    policy=\$(chrt -p "\$pid" 2>/dev/null | grep -o 'SCHED_[A-Z]*')
    [ "\$policy" != "SCHED_FIFO" ] && chrt -f -p 50 "\$pid" 2>/dev/null && \\
        logger -t ktp-chrt "Applied SCHED_FIFO 50 to port \$port PID \$pid"
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
echo ""
echo "To check pinning status:"
echo '  for pid in $(pgrep -f hlds_linux); do port=$(tr '"'"'\0'"'"' '"'"' '"'"' < /proc/$pid/cmdline | grep -oP '"'"'(?<=-port )\d+'"'"'); [ -z "$port" ] && continue; echo "Port $port: $(taskset -cp $pid 2>/dev/null) | $(chrt -p $pid 2>/dev/null | head -1)"; done'
