#!/bin/bash
# lan-hltv-tunnel.sh — expose a LAN box's HLTV proxies AND the web overlay to the
# internet through a public frp relay, so online viewers can spectate and a REMOTE
# caster/OBS can reach the overlay even when the box sits behind venue NAT with NO
# inbound port-forward available.
#
#   spectator   ──UDP──> RELAY:2802N ──frps──tunnel──frpc──> box 127.0.0.1:2702N (HLTV)
#   remote OBS  ──TCP──> RELAY:28080 ──frps──tunnel──frpc──> box 127.0.0.1:8080  (overlay)
#
# Two modes (run the relay side first — it mints the shared token):
#
#   # on the public relay host (e.g. the KTP data server):
#   sudo bash lan-hltv-tunnel.sh relay
#       -> installs frps, generates /opt/frp/token, opens fw 7000/tcp + 28020-28024/udp,
#          prints the token + the exact client command to run next.
#
#   # on the LAN box:
#   sudo RELAY_HOST=<relay-public-ip> TUNNEL_TOKEN=<token-from-relay> bash lan-hltv-tunnel.sh client
#       -> installs frpc (on the bulk disk), maps HLTV 27020-24 -> relay 28020-24 +
#          overlay 8080 -> relay 28080, starts it. Overlay: http://<relay>:28080/screen
#
# The token is NEVER stored in this script (public repo) — it is generated on the
# relay and passed to the client via env. Idempotent; does not restart game servers.
#
# Env: HLTV_PORTS ("27020 27021 27022 27023 27024"), PUBLIC_BASE (28020 — remote port
#   base, remote = PUBLIC_BASE + index), CTRL_PORT (7000), FRP_DIR (relay /opt/frp,
#   client /srv/ktpdata/frp), GAMEUSER (dodserver).
set -euo pipefail

MODE="${1:-}"
HLTV_PORTS="${HLTV_PORTS:-27020 27021 27022 27023 27024}"
PUBLIC_BASE="${PUBLIC_BASE:-28020}"
CTRL_PORT="${CTRL_PORT:-7000}"
GAMEUSER="${GAMEUSER:-dodserver}"
# Web overlay (nginx single-origin on the box) tunnelled as TCP for a REMOTE caster/OBS.
# WEB_LOCAL=0 disables it (in-room OBS needs no tunnel).
WEB_LOCAL="${WEB_LOCAL:-8080}"
WEB_PUBLIC="${WEB_PUBLIC:-28080}"

frp_install() {  # $1 = dir
  local dir="$1"
  mkdir -p "$dir"
  if [ ! -x "$dir/frps" ] && [ ! -x "$dir/frpc" ]; then
    local ver
    ver=$(curl -s https://api.github.com/repos/fatedier/frp/releases/latest | grep -oP '"tag_name": "v\K[^"]+')
    echo "[frp] installing v$ver"
    curl -fsSL -o /tmp/frp.tar.gz "https://github.com/fatedier/frp/releases/download/v${ver}/frp_${ver}_linux_amd64.tar.gz"
    tar xzf /tmp/frp.tar.gz -C "$dir" --strip-components=1
  fi
}

case "$MODE" in
  relay)
    FRP_DIR="${FRP_DIR:-/opt/frp}"
    frp_install "$FRP_DIR"
    [ -f "$FRP_DIR/token" ] || openssl rand -hex 20 > "$FRP_DIR/token"
    chmod 600 "$FRP_DIR/token"
    TOKEN="$(cat "$FRP_DIR/token")"
    cat > "$FRP_DIR/frps.toml" <<EOF
bindPort = $CTRL_PORT
auth.method = "token"
auth.token = "$TOKEN"
EOF
    cat > /etc/systemd/system/frps.service <<UNIT
[Unit]
Description=frp server (KTP LAN HLTV relay)
After=network.target
[Service]
Type=simple
ExecStart=$FRP_DIR/frps -c $FRP_DIR/frps.toml
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload; systemctl enable --now frps >/dev/null 2>&1; systemctl restart frps
    ufw allow "$CTRL_PORT/tcp" comment 'frp control (KTP LAN HLTV relay)' >/dev/null 2>&1 || true
    i=0; for _ in $HLTV_PORTS; do ufw allow "$((PUBLIC_BASE+i))/udp" comment 'KTP LAN HLTV public via frp' >/dev/null 2>&1 || true; i=$((i+1)); done
    [ "$WEB_LOCAL" != 0 ] && ufw allow "$WEB_PUBLIC/tcp" comment 'KTP LAN HUD overlay public via frp' >/dev/null 2>&1 || true
    RHOST=$(hostname -I | awk '{print $1}')
    echo ""
    echo "[relay] frps active on :$CTRL_PORT — public HLTV ports $PUBLIC_BASE-$((PUBLIC_BASE+i-1))/udp$([ "$WEB_LOCAL" != 0 ] && echo ", overlay $WEB_PUBLIC/tcp")"
    echo "[relay] TOKEN: $TOKEN"
    echo "[relay] now on the LAN box run:"
    echo "        sudo RELAY_HOST=<this-host-public-ip> TUNNEL_TOKEN=$TOKEN bash lan-hltv-tunnel.sh client"
    ;;

  client)
    : "${RELAY_HOST:?set RELAY_HOST=<relay public ip>}"
    : "${TUNNEL_TOKEN:?set TUNNEL_TOKEN=<token printed by the relay>}"
    FRP_DIR="${FRP_DIR:-/srv/ktpdata/frp}"
    frp_install "$FRP_DIR"
    {
      echo "serverAddr = \"$RELAY_HOST\""
      echo "serverPort = $CTRL_PORT"
      echo "auth.method = \"token\""
      echo "auth.token = \"$TUNNEL_TOKEN\""
      i=0
      for p in $HLTV_PORTS; do
        printf '\n[[proxies]]\nname = "hltv-%s"\ntype = "udp"\nlocalIP = "127.0.0.1"\nlocalPort = %s\nremotePort = %s\n' "$p" "$p" "$((PUBLIC_BASE+i))"
        i=$((i+1))
      done
      # web overlay as TCP (single-origin nginx :8080 → public port); WebSocket/socket.io passes through TCP fine
      [ "$WEB_LOCAL" != 0 ] && printf '\n[[proxies]]\nname = "hud-overlay"\ntype = "tcp"\nlocalIP = "127.0.0.1"\nlocalPort = %s\nremotePort = %s\n' "$WEB_LOCAL" "$WEB_PUBLIC"
    } > "$FRP_DIR/frpc.toml"
    chown -R "$GAMEUSER:$GAMEUSER" "$FRP_DIR"
    cat > /etc/systemd/system/frpc.service <<UNIT
[Unit]
Description=frp client (KTP LAN HLTV relay to $RELAY_HOST)
After=network.target
[Service]
Type=simple
User=$GAMEUSER
ExecStart=$FRP_DIR/frpc -c $FRP_DIR/frpc.toml
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload; systemctl enable --now frpc >/dev/null 2>&1; systemctl restart frpc
    sleep 3
    echo "[client] frpc: $(systemctl is-active frpc) — HLTV $HLTV_PORTS -> $RELAY_HOST:$PUBLIC_BASE+"
    echo "[client] viewers spectate with:  connect $RELAY_HOST:$PUBLIC_BASE   (LAN 1; +1 per instance)"
    [ "$WEB_LOCAL" != 0 ] && echo "[client] remote OBS/overlay:      http://$RELAY_HOST:$WEB_PUBLIC/screen?server=KTP%20LAN%201"
    ;;

  *)
    echo "usage: $0 relay        (on the public relay host — prints the token)"
    echo "       RELAY_HOST=.. TUNNEL_TOKEN=.. $0 client   (on the LAN box)"
    exit 1 ;;
esac
