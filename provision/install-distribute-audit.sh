#!/usr/bin/env bash
# Install write attribution for /home/dod/distribute on the DATA SERVER.
#
# Run as root on the data server. Idempotent.
#
# What this buys: `ausearch -k ktp-distribute-cfg -i` names the uid, the login
# uid, the pid and the executable behind a write to the fleet deploy path.
# sshd's own logs cannot do this -- they identify a session, not which session
# touched a file -- and the distributor's logs record the event without the
# actor.

set -euo pipefail

RULES_SRC="$(dirname "$(readlink -f "$0")")/audit-distribute.rules"
RULES_DST=/etc/audit/rules.d/50-ktp-distribute.rules
WATCH_DIR=/home/dod/distribute

if [ "$(id -u)" -ne 0 ]; then
    echo "FATAL: run as root." >&2
    exit 1
fi

# A rule against a path that does not exist loads but never fires, and reads as
# "nothing ever wrote there" -- the same output as working attribution.
if [ ! -d "$WATCH_DIR" ]; then
    echo "FATAL: $WATCH_DIR does not exist. This script is for the data server." >&2
    exit 1
fi

if ! dpkg -s auditd >/dev/null 2>&1; then
    echo "Installing auditd..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y auditd
fi

install -m 0640 -o root -g root "$RULES_SRC" "$RULES_DST"
augenrules --load
systemctl enable --now auditd

# Verify the rules are LOADED, not merely written. augenrules exits 0 having
# skipped a rule the running kernel rejected.
echo
echo "Loaded rules:"
auditctl -l | grep -F ktp-distribute || {
    echo "FATAL: rules are on disk but not in the kernel." >&2
    echo "       Check 'auditctl -s' for enabled=2 (immutable until reboot)." >&2
    exit 2
}

echo
echo "NOT self-tested on purpose. Any write under $WATCH_DIR -- including a probe"
echo "file -- is distributed to all 24 instances within ~15s, so there is no"
echo "harmless way to fire this rule. The next real deploy is the test."
echo
echo "Read attribution with:  ausearch -k ktp-distribute-cfg -i"
