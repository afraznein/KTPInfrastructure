#!/bin/bash
# KTP LAN admin helper — one script, many subcommands, driven by the desktop
# launchers (or run directly). Run as the dodserver user.
#
# Usage: lan-admin.sh <command>
#   details   LinuxGSM 'details' for every game server (ports, IP, connect info)
#   status    Up/down + player counts across all servers
#   console   Attach to a server's live console (pick which)
#   restart   Restart a server / all / warmup (each behind a confirm)
#   hltv      HLTV proxy status + most recent demo writes
#   warmup    The stock warmup server: details / console / start / stop
#   perf      Live system monitor (htop) + per-instance fps sweep
#   ip        Show this box's LAN IP(s)
#   changeip  Retarget the whole stack to a new bind IP (venue day; needs root)
#   editconf  Open lan-deploy.conf in a text editor
#   menu      Interactive menu of all of the above (default)

set -u

# --- config ------------------------------------------------------------------
# Competitive instances auto-discovered from ~/dod-* (LinuxGSM trees).
# Warmup server tree (stock 32-slot). Override with WARMUP_DIR=... if elsewhere.
WARMUP_DIR="${WARMUP_DIR:-/srv/ktpdata/warmup}"
CONF="${LAN_CONF:-$HOME/lan-deploy.conf}"

pause() { echo; read -rp "Press Enter to close..." _; }

# The LinuxGSM launcher inside an instance dir (dodserver, dodserver2, ...).
gsm_exe() { find "$1" -maxdepth 1 -type f -name 'dodserver*' -perm -u+x 2>/dev/null | head -1; }

# Competitive instance dirs, sorted by port.
instances() { ls -d "$HOME"/dod-* 2>/dev/null | sort; }

run_gsm() {  # run_gsm <instance_dir> <gsm-cmd...>
    local dir="$1"; shift
    local exe; exe=$(gsm_exe "$dir")
    [ -n "$exe" ] || { echo "  (no LinuxGSM launcher found in $dir)"; return 1; }
    ( cd "$dir" && ./"$(basename "$exe")" "$@" )
}

cmd_details() {
    for d in $(instances); do
        echo "======================================================================"
        echo "  $(basename "$d")"
        echo "======================================================================"
        run_gsm "$d" details
        echo
    done
    if [ -d "$WARMUP_DIR" ]; then
        echo "======================================================================"
        echo "  WARMUP: $(basename "$WARMUP_DIR")"
        echo "======================================================================"
        run_gsm "$WARMUP_DIR" details
    fi
    pause
}

cmd_status() {
    if [ -x "$HOME/status.sh" ]; then
        "$HOME/status.sh"
    else
        for d in $(instances) "$WARMUP_DIR"; do
            [ -d "$d" ] || continue
            local port name up
            port=$(basename "$d" | sed 's/dod-//')
            if pgrep -f "hlds_linux.*-port $port" >/dev/null 2>&1; then up="UP  "; else up="DOWN"; fi
            printf "  [%s] %s (port %s)\n" "$up" "$(basename "$d")" "$port"
        done
        echo
        echo "(Live player counts need a game query; run 'details' for connect info.)"
    fi
    pause
}

cmd_console() {
    local dirs=() d n=1
    for d in $(instances); do dirs+=("$d"); done
    [ -d "$WARMUP_DIR" ] && dirs+=("$WARMUP_DIR")
    echo "Attach to which server console?"
    for d in "${dirs[@]}"; do printf "  %d) %s\n" "$n" "$(basename "$d")"; n=$((n+1)); done
    echo "  q) cancel"
    read -rp "> " pick
    [ "$pick" = q ] && return 0
    local sel="${dirs[$((pick-1))]:-}"
    [ -n "$sel" ] || { echo "invalid"; pause; return; }
    echo "Attaching to $(basename "$sel") — detach with Ctrl+b then d"
    run_gsm "$sel" console
}

cmd_restart() {
    local dirs=() d n=1
    for d in $(instances); do dirs+=("$d"); done
    [ -d "$WARMUP_DIR" ] && dirs+=("$WARMUP_DIR")
    echo "Restart what?"
    echo "  a) ALL competitive servers"
    for d in "${dirs[@]}"; do printf "  %d) %s\n" "$n" "$(basename "$d")"; n=$((n+1)); done
    echo "  q) cancel"
    read -rp "> " pick
    [ "$pick" = q ] && return 0
    if [ "$pick" = a ]; then
        read -rp "Restart ALL competitive servers? This drops any live match. [y/N] " c
        [ "$c" = y ] || { echo "cancelled"; pause; return; }
        if [ -x "$HOME/restart-all-servers.sh" ]; then "$HOME/restart-all-servers.sh"; else
            for d in $(instances); do run_gsm "$d" restart; done
        fi
        pause; return
    fi
    local sel="${dirs[$((pick-1))]:-}"
    [ -n "$sel" ] || { echo "invalid"; pause; return; }
    read -rp "Restart $(basename "$sel")? [y/N] " c
    [ "$c" = y ] || { echo "cancelled"; pause; return; }
    run_gsm "$sel" restart
    pause
}

cmd_hltv() {
    echo "== HLTV proxy processes =="
    pgrep -a -f 'hltv' 2>/dev/null || echo "  (no hltv processes found)"
    echo
    echo "== Most recent demo files =="
    local demodir
    for demodir in /home/hltvserver/hlds/dod /srv/ktpdata/hltvserver/hlds/dod; do
        if [ -d "$demodir" ]; then
            echo "  $demodir:"
            ls -lt "$demodir"/*.dem 2>/dev/null | head -8 || echo "    (no .dem files yet)"
        fi
    done
    pause
}

cmd_warmup() {
    if [ ! -d "$WARMUP_DIR" ]; then
        echo "Warmup server not found at $WARMUP_DIR (set WARMUP_DIR if elsewhere)."
        pause; return
    fi
    echo "Warmup server ($WARMUP_DIR):"
    echo "  1) details   2) console   3) start   4) stop   5) restart   q) cancel"
    read -rp "> " pick
    case "$pick" in
        1) run_gsm "$WARMUP_DIR" details; pause ;;
        2) run_gsm "$WARMUP_DIR" console ;;
        3) run_gsm "$WARMUP_DIR" start; pause ;;
        4) run_gsm "$WARMUP_DIR" stop; pause ;;
        5) run_gsm "$WARMUP_DIR" restart; pause ;;
        *) : ;;
    esac
}

cmd_perf() {
    echo "== Load / memory =="
    uptime; echo; free -h; echo
    echo "== Per-instance processes (pinned CPU shown as PSR) =="
    ps -eo pid,psr,pcpu,pmem,comm | grep -E 'hlds_linux|PID' | grep -v grep
    echo
    if command -v htop >/dev/null 2>&1; then
        echo "Launching htop (q to quit)..."; sleep 1; htop
    else
        echo "htop not installed — showing top instead (q to quit)..."; sleep 1; top
    fi
}

cmd_ip() {
    if [ -x "$HOME/lan-show-ip.sh" ]; then "$HOME/lan-show-ip.sh"; else
        echo "Primary LAN IP:"; hostname -I | awk '{print $1}'
    fi
    pause
}

cmd_changeip() {
    # Venue-day retarget to a new bind IP. Needs root (edits configs across
    # dodserver/hltvserver/warmup + the stats DB + restarts servers), so it
    # sudo's the dedicated tool — a full lan-deploy re-run CANNOT change the IP
    # on a live box (see LAN-DEPLOY.md). Runs AS the GUI user; sudo prompts.
    local tool=/opt/ktp/KTPInfrastructure/provision/lan-change-ip.sh
    if [ ! -x "$tool" ]; then echo "lan-change-ip.sh not found at $tool"; pause; return; fi
    local cur
    cur=$(grep -E '^LAN_IP=' /opt/ktp/KTPInfrastructure/provision/lan-deploy.conf 2>/dev/null | cut -d= -f2 | tr -d '"')
    echo "Retarget the LAN stack to a new bind IP (venue day)."
    echo "  Configured IP: ${cur:-unknown}"
    echo "  Local IP(s)  : $(hostname -I)"
    read -rp "New venue IP (blank = cancel): " ip
    [ -n "$ip" ] || { echo "cancelled"; pause; return; }
    echo; echo "--- preview (dry run) ---"
    sudo "$tool" "$ip" --dry-run
    echo
    read -rp "Apply this change and restart all servers? [y/N] " ok
    case "$ok" in
        y|Y|yes|YES) echo; sudo "$tool" "$ip" ;;
        *) echo "cancelled — no changes made" ;;
    esac
    pause
}

cmd_editconf() {
    if [ ! -e "$CONF" ]; then echo "Config not found at $CONF"; pause; return; fi
    if command -v gnome-text-editor >/dev/null 2>&1; then gnome-text-editor "$CONF"
    elif command -v gedit >/dev/null 2>&1; then gedit "$CONF"
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$CONF"
    else "${EDITOR:-nano}" "$CONF"; fi
}

cmd_menu() {
    while true; do
        clear 2>/dev/null || true
        echo "==================== KTP LAN Admin ===================="
        echo "  1) Server details (all)      6) HLTV status"
        echo "  2) Live status               7) Warmup server"
        echo "  3) Attach to a console       8) Perf / system monitor"
        echo "  4) Restart (server/all)      9) Show LAN IP"
        echo "  5) Edit LAN config           c) Change LAN IP (venue)"
        echo "                               q) quit"
        echo "======================================================="
        read -rp "> " pick
        case "$pick" in
            1) cmd_details ;; 2) cmd_status ;; 3) cmd_console ;; 4) cmd_restart ;;
            5) cmd_editconf ;; 6) cmd_hltv ;; 7) cmd_warmup ;; 8) cmd_perf ;;
            9) cmd_ip ;; c|C) cmd_changeip ;; q|Q) break ;; *) : ;;
        esac
    done
}

case "${1:-menu}" in
    details) cmd_details ;;
    status)  cmd_status ;;
    console) cmd_console ;;
    restart) cmd_restart ;;
    hltv)    cmd_hltv ;;
    warmup)  cmd_warmup ;;
    perf)    cmd_perf ;;
    ip)      cmd_ip ;;
    changeip) cmd_changeip ;;
    editconf) cmd_editconf ;;
    menu|*)  cmd_menu ;;
esac
