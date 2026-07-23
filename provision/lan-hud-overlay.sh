#!/bin/bash
# lan-hud-overlay.sh — provision the DoD HUD Observer broadcast overlay on a LAN box.
#
# Stands up Jimmy Lockhart's 3-tier overlay stack (KTPHudObserver plugin already
# ships with the game servers; this is the receiving half):
#
#   KTPHudObserver.amxx  --HTTP JSON-->  Node backend (ingest/REST/Socket.IO)
#                                          |
#                                   React frontend  <--single-origin nginx-->  OBS
#
# Everything runs ON the box (self-contained — no internet dependency once built),
# installed on the BULK disk (/srv/ktpdata) so node_modules/build/match recordings
# never touch the small OS root. Single-origin nginx on :8080 keeps the frontend's
# Socket.IO/REST same-origin (OBS's CEF blocks mixed content otherwise) and — with
# the same-origin source patch below — makes the whole thing IP-portable: the
# frontend resolves the backend from window.location.origin, so a venue IP change
# needs NOTHING here (the overlay + frp tunnel both keep working; only the game/
# HLTV/HLStatsX side needs lan-change-ip.sh).
#
# Idempotent: safe to re-run. Does NOT restart game servers (loading the plugin
# cfg needs a restart — see the note printed at the end / --restart-servers flag).
#
# Usage:
#   sudo BOXIP=<box-lan-ip> bash lan-hud-overlay.sh [--restart-servers]
#
# Env overrides: BOXIP (frontend origin host, default = first non-lo IPv4),
#   BASE (default /srv/ktpdata/hud-observer), WEBPORT (8080), INGEST (8088),
#   APIPORT (3001), SOCKPORT (4000), REPO (Jimmy's repo), INSTANCES ("27015..27019").
set -euo pipefail

BASE="${BASE:-/srv/ktpdata/hud-observer}"
APP="$BASE/app"
REPO="${REPO:-https://github.com/JimmyLockhart65616/DoD-hud-observer.git}"
WEBPORT="${WEBPORT:-8080}"; INGEST="${INGEST:-8088}"; APIPORT="${APIPORT:-3001}"; SOCKPORT="${SOCKPORT:-4000}"
GAMEUSER="${GAMEUSER:-dodserver}"
INSTANCES="${INSTANCES:-27015 27016 27017 27018 27019}"
BOXIP="${BOXIP:-$(hostname -I | tr ' ' '\n' | grep -vE '^$|^127|:' | head -1)}"
RESTART=0; [ "${1:-}" = "--restart-servers" ] && RESTART=1

echo "== KTP LAN HUD overlay provision =="
echo "   base=$BASE  boxip=$BOXIP  web=:$WEBPORT  ingest=:$INGEST"

# ── 1. toolchain (git + Node 20) ────────────────────────────────────────────
command -v git  >/dev/null || { echo "[deps] installing git";  DEBIAN_FRONTEND=noninteractive apt-get install -y git >/dev/null; }
if ! command -v node >/dev/null || [ "$(node -v | grep -oE '[0-9]+' | head -1)" -lt 18 ]; then
  echo "[deps] installing Node 20 (nodesource)"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null 2>&1
  apt-get install -y nodejs >/dev/null
fi
echo "   node $(node -v)  npm $(npm -v)"

# ── 2. install dir on bulk disk + clone/update ──────────────────────────────
mkdir -p "$BASE/matches" "$BASE/logs"
chown -R "$GAMEUSER:$GAMEUSER" "$BASE"
su -l "$GAMEUSER" -c "npm config set cache '$BASE/.npm'"
if [ -d "$APP/.git" ]; then
  su -l "$GAMEUSER" -c "cd '$APP' && git fetch --depth 1 origin && git reset --hard origin/HEAD" >/dev/null 2>&1 || true
else
  su -l "$GAMEUSER" -c "rm -rf '$APP' && git clone --depth 1 '$REPO' '$APP'" >/dev/null 2>&1
fi
echo "[repo] $(su -l "$GAMEUSER" -c "cd '$APP' && git rev-parse --short HEAD") checked out"

# ── 3. same-origin frontend patch (IP-portable — falls back to window.location.origin)
sed -i "s#process.env.REACT_APP_SOCKET_URL || 'http://localhost:4000'#process.env.REACT_APP_SOCKET_URL || window.location.origin#" \
  "$APP/web/src/components/core/Socket/Socket.jsx"
sed -i "s#process.env.REACT_APP_API_URL || 'http://localhost:3001'#process.env.REACT_APP_API_URL || window.location.origin#g" \
  "$APP/web/src/components/core/Replay/Replay.jsx" "$APP/web/src/components/matchPicker/MatchPicker.jsx"

# ── 4. build (root deps need --legacy-peer-deps: react-bootstrap@1.5.2 vs react@19)
echo "[build] npm install + react build (several minutes)…"
su -l "$GAMEUSER" -c "cd '$APP' && npm install --legacy-peer-deps --no-audit --no-fund >/dev/null 2>&1"
su -l "$GAMEUSER" -c "cd '$APP/web' && CI=false GENERATE_SOURCEMAP=false npm run build >/dev/null 2>&1"
[ -f "$APP/web/build/index.html" ] || { echo "ABORT: web build failed"; exit 1; }
echo "[build] ok ($(du -sh "$APP/web/build" | cut -f1))"

# ── 5. auth key (generated once, shared by backend + plugin cfg) ─────────────
if [ ! -f "$BASE/.authkey" ]; then openssl rand -hex 24 > "$BASE/.authkey"; fi
chmod 600 "$BASE/.authkey"; chown "$GAMEUSER:$GAMEUSER" "$BASE/.authkey"
KEY="$(cat "$BASE/.authkey")"

# ── 6. backend systemd unit ─────────────────────────────────────────────────
cat > /etc/systemd/system/ktp-hud-backend.service <<UNIT
[Unit]
Description=KTP HUD Observer backend (ingest + REST + Socket.IO)
After=network.target

[Service]
Type=simple
User=$GAMEUSER
WorkingDirectory=$APP
ExecStart=/usr/bin/npx ts-node --script-mode $APP/backend/src/app.ts
Restart=on-failure
RestartSec=3
Environment=NODE_ENV=production
Environment=HUD_AUTH_KEY=$KEY
Environment=HUD_INGEST_PORT=$INGEST
Environment=HUD_API_PORT=$APIPORT
Environment=HUD_SOCKET_PORT=$SOCKPORT
Environment=HUD_MATCHES_DIR=$BASE/matches
Environment=HUD_FRONTEND_ORIGIN=http://$BOXIP:$WEBPORT
Environment=HUD_HLTV_SYNC_ENABLED=false
StandardOutput=append:$BASE/logs/backend.log
StandardError=append:$BASE/logs/backend-err.log

[Install]
WantedBy=multi-user.target
UNIT

# ── 7. nginx single-origin :$WEBPORT (leaves FastDL :80 untouched) ───────────
cat > /etc/nginx/conf.d/ktp-hud.conf <<NGINX
# KTP HUD Observer overlay — single-origin on :$WEBPORT
map \$http_upgrade \$ktp_hud_upgrade { default upgrade; '' close; }
server {
    listen $WEBPORT;
    listen [::]:$WEBPORT;
    server_name _;
    root $APP/web/build;
    index index.html;
    location /socket.io/ {
        proxy_pass http://127.0.0.1:$SOCKPORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$ktp_hud_upgrade;
        proxy_set_header Host \$host;
        proxy_read_timeout 3600s;
    }
    location ~ ^/(api/|health\$|metrics\$) {
        proxy_pass http://127.0.0.1:$APIPORT;
        proxy_set_header Host \$host;
    }
    location / { try_files \$uri \$uri/ /index.html; }
}
NGINX

# ── 8. plugin hud_observer.cfg on every instance + exec from the REAL boot cfg ─
# The boot cfg is always the +servercfgfile the game launched with (dodserver.cfg
# on this fleet) — NOT the LinuxGSM-default dodserverN.cfg leftovers, which the
# game never reads. Target it directly; do not guess by grepping for sv_password.
for p in $INSTANCES; do
  D="/home/$GAMEUSER/dod-$p/serverfiles/dod"
  [ -d "$D" ] || { echo "[cfg] $p: no game tree, skipping"; continue; }
  HC="$D/addons/ktpamx/configs/hud_observer.cfg"
  printf 'dod_hud_url "http://127.0.0.1:%s/ingest"\ndod_hud_key "%s"\n' "$INGEST" "$KEY" > "$HC"
  chown "$GAMEUSER:$GAMEUSER" "$HC"
  BOOT="$D/dodserver.cfg"
  grep -q 'hud_observer.cfg' "$BOOT" 2>/dev/null || \
    printf '\n// KTP HUD overlay ingest config\nexec addons/ktpamx/configs/hud_observer.cfg\n' >> "$BOOT"
done

# ── 9. firewall (only the OBS port; ingest/api/socket stay localhost) ────────
ufw allow "$WEBPORT/tcp" comment 'KTP HUD overlay (OBS)' >/dev/null 2>&1 || true

# ── 10. start ───────────────────────────────────────────────────────────────
systemctl daemon-reload
systemctl enable --now ktp-hud-backend >/dev/null 2>&1
systemctl restart ktp-hud-backend
nginx -t >/dev/null 2>&1 && systemctl reload nginx

echo ""
echo "== done =="
echo "   overlay:  http://$BOXIP:$WEBPORT/screen?server=<hostname>   (OBS browser source)"
echo "   picker:   http://$BOXIP:$WEBPORT/"
echo "   auth key: $BASE/.authkey"
if [ "$RESTART" = "1" ]; then
  echo "== restarting game servers to load hud_observer.cfg =="
  for p in $INSTANCES; do
    n=$((p-27014)); sel="dodserver"; [ "$n" -gt 1 ] && sel="dodserver$n"
    su -l "$GAMEUSER" -c "~/dod-$p/$sel restart" >/dev/null 2>&1 && echo "   $p restarted"
  done
else
  echo "!! Game servers must be restarted to load the plugin cfg (not done automatically)."
  echo "   Re-run with --restart-servers, or restart each instance when ready."
fi
