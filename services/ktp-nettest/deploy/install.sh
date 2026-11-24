#!/usr/bin/env bash
# Installs or updates ktp-nettest on this host. Idempotent: safe to re-run after a git pull.
# It NEVER enables, starts or restarts the service; that is a separate, deliberate step
# (README, Deploy). It never overwrites /etc/ktp/nettest.env or an existing drop-in.
#
#   sudo bash deploy/install.sh            # from a checkout of services/ktp-nettest
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST=/opt/ktp-nettest
UNIT=/etc/systemd/system/ktp-nettest.service
DROPIN_DIR=/etc/systemd/system/ktp-nettest.service.d
ENVFILE=/etc/ktp/nettest.env
SVC_USER=ktpnettest
NODE_MIN=20

die() { echo "install.sh: $*" >&2; exit 1; }
say() { echo "install.sh: $*"; }

[ "$(id -u)" -eq 0 ] || die "run as root"
[ -f "$SRC/server.js" ] && [ -f "$SRC/package-lock.json" ] || die "$SRC is not services/ktp-nettest"

command -v node >/dev/null || die "node not found; install Node.js $NODE_MIN or newer first (Ubuntu 24.04's nodejs is 18)"
[ "$(command -v node)" = /usr/bin/node ] || die "node is $(command -v node); the unit runs /usr/bin/node"
node_major="$(node -p 'process.versions.node.split(".")[0]')"
[ "$node_major" -ge "$NODE_MIN" ] || die "node $(node -v) is too old; package.json needs >= $NODE_MIN"
command -v npm >/dev/null || die "npm not found"

if ! id "$SVC_USER" >/dev/null 2>&1; then
  useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$SVC_USER"
  say "created system user $SVC_USER"
fi

changed=0
# copy_if_changed SRC DST MODE: installs only when the bytes differ, and says which.
copy_if_changed() {
  if [ -f "$2" ] && cmp -s "$1" "$2"; then return 0; fi
  install -D -m "$3" -o root -g root "$1" "$2"
  say "installed $2"
  changed=1
}

for f in server.js client.js frame.js package.json package-lock.json lib/ticket.js lib/busy.js; do
  copy_if_changed "$SRC/$f" "$DEST/$f" 0644
done
if [ "$changed" -eq 1 ] || [ ! -d "$DEST/node_modules" ]; then
  (cd "$DEST" && npm ci --omit=dev --ignore-scripts --no-audit --no-fund)
  say "dependencies installed in $DEST/node_modules"
fi

unit_changed=0
changed=0
copy_if_changed "$SRC/deploy/ktp-nettest.service" "$UNIT" 0644
[ "$changed" -eq 1 ] && unit_changed=1

if [ ! -e "$DROPIN_DIR/logdirs.conf" ]; then
  install -D -m 0644 -o root -g root "$SRC/deploy/ktp-nettest.service.d/logdirs.conf.example" "$DROPIN_DIR/logdirs.conf"
  say "installed $DROPIN_DIR/logdirs.conf from the example; edit it for this host"
  unit_changed=1
else
  say "kept existing $DROPIN_DIR/logdirs.conf"
fi
for p in $(sed -n 's/^BindReadOnlyPaths=-\{0,1\}//p' "$DROPIN_DIR/logdirs.conf"); do
  [ -d "$p" ] || say "WARNING: $p does not exist; the unit will refuse to start until logdirs.conf is fixed"
done

if [ ! -e "$ENVFILE" ]; then
  install -D -m 0600 -o root -g root "$SRC/deploy/nettest.env.example" "$ENVFILE"
  say "installed $ENVFILE from the example; set the secret and region before starting"
else
  chmod 0600 "$ENVFILE"
  chown root:root "$ENVFILE"
  say "kept existing $ENVFILE"
fi
if grep -Eiq '^KTP_NETTEST_TICKET_SECRET=.*(placeholder|replace|changeme)' "$ENVFILE"; then
  say "NOTE: $ENVFILE still has the placeholder secret; the node will refuse to start"
fi

if [ "$unit_changed" -eq 1 ]; then
  systemctl daemon-reload
  say "systemd reloaded (service not enabled, not started)"
fi
systemd-analyze verify "$UNIT" || say "WARNING: systemd-analyze verify reported problems above"

say "done. Not enabled, not started: see README, Deploy, for the remaining steps."
