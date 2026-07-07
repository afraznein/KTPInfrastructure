#!/usr/bin/env python3
"""Stage `mp_logecho 0` into every instance's game dodserver.cfg (R4).

Suppresses the qconsole game-thread sync write (log events echoed to console
when mp_logecho defaults to 1 and LinuxGSM consolelogging keeps -condebug on).
L-file + UDP logaddress (what HLStatsX/telemetry read) are unaffected; direct
Con_Printf output ([KTP_PROFILE], DODX diag, cvar-query replies incl. the R8
assert) is also unaffected — mp_logecho only gates Log_Printf echo.

Idempotent: skips instances that already have an `^mp_logecho` line. Backs up
dodserver.cfg before editing. Inert until the cfg is re-exec'd (map change or
restart), so it activates at the next deploy restart. Verifies after.

Password: $KTP_FLEET_SSH_PASSWORD or ~/.ktp_fleet_ssh_password (never hardcoded).

Usage: stage-mp-logecho.py [--hosts atlanta,dallas] [--dry-run]
"""
import argparse
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    import paramiko
except ImportError:
    print("ERROR: paramiko not installed. Run: pip install paramiko")
    sys.exit(1)

SERVERS = {
    'atlanta': '74.91.121.9',
    'dallas':  '74.91.126.55',
    'denver':  '66.163.114.109',
    'newyork': '74.91.123.64',
    'chicago': '172.238.176.101',
}

CFG_REL = "serverfiles/dod/dodserver.cfg"
LINE = "mp_logecho 0                        // qconsole log echo off (game-thread sync write); L-log+logaddress unaffected"


def fleet_password():
    pw = os.environ.get('KTP_FLEET_SSH_PASSWORD')
    if not pw:
        p = os.path.expanduser('~/.ktp_fleet_ssh_password')
        if os.path.exists(p):
            pw = open(p).read().strip()
    if not pw:
        raise SystemExit('set $KTP_FLEET_SSH_PASSWORD or ~/.ktp_fleet_ssh_password')
    return pw


# Remote shell: for each dod-* instance, idempotently add mp_logecho 0.
REMOTE = r'''
STAMP=$(date +%Y%m%d-%H%M%S)
ADDED=0; SKIP=0; ERR=0
for d in ~/dod-2701*; do
  [ -d "$d" ] || continue
  CFG="$d/{cfg_rel}"
  port=$(basename "$d")
  if [ ! -f "$CFG" ]; then echo "  [$port] NO cfg at $CFG"; ERR=$((ERR+1)); continue; fi
  if grep -qE '^[[:space:]]*mp_logecho' "$CFG"; then
    echo "  [$port] already has mp_logecho -> skip"; SKIP=$((SKIP+1)); continue
  fi
  cp "$CFG" "$CFG.bak-mplogecho-$STAMP" || { echo "  [$port] backup FAILED"; ERR=$((ERR+1)); continue; }
  if grep -qE '^sv_logecho' "$CFG"; then
    sed -i '/^sv_logecho/a {line}' "$CFG"
  elif grep -qE '^log on' "$CFG"; then
    sed -i '/^log on/a {line}' "$CFG"
  else
    printf '\n%s\n' '{line}' >> "$CFG"
  fi
  n=$(grep -cE '^[[:space:]]*mp_logecho[[:space:]]+0' "$CFG")
  if [ "$n" -eq 1 ]; then echo "  [$port] added mp_logecho 0 (backup .bak-mplogecho-$STAMP)"; ADDED=$((ADDED+1));
  else
    echo "  [$port] VERIFY FAILED (count=$n) — restoring"
    cp "$CFG.bak-mplogecho-$STAMP" "$CFG" || echo "  [$port] RESTORE FAILED — fix $CFG by hand from $CFG.bak-mplogecho-$STAMP"
    ERR=$((ERR+1))
  fi
done
echo "SUMMARY added=$ADDED skipped=$SKIP errors=$ERR"
'''.replace('{cfg_rel}', CFG_REL).replace('{line}', LINE)

DRY = r'''
for d in ~/dod-2701*; do
  [ -d "$d" ] || continue
  CFG="$d/{cfg_rel}"; port=$(basename "$d")
  if [ ! -f "$CFG" ]; then echo "  [$port] NO cfg"; continue; fi
  if grep -qE '^[[:space:]]*mp_logecho' "$CFG"; then echo "  [$port] already has mp_logecho";
  else echo "  [$port] WOULD add mp_logecho 0 (current logging lines:)"; grep -nE '^(log on|sv_logecho|mp_logecho|sv_logfile)' "$CFG" | sed 's/^/      /'; fi
done
'''.replace('{cfg_rel}', CFG_REL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hosts')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    targets = list(SERVERS) if not args.hosts else [h.strip() for h in args.hosts.split(',')]
    for t in targets:
        if t not in SERVERS:
            raise SystemExit(f"unknown host '{t}' (know: {', '.join(SERVERS)})")
    pw = fleet_password()
    cmd = DRY if args.dry_run else REMOTE
    print("MODE:", "DRY-RUN" if args.dry_run else "LIVE (stage, inert until restart/map-change)")
    for name in targets:
        print(f"\n===== {name} ({SERVERS[name]}) =====")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(SERVERS[name], username='dodserver', password=pw, timeout=20)
            _, out, err = ssh.exec_command(cmd, timeout=120)
            print(out.read().decode(errors='replace').rstrip())
            e = err.read().decode(errors='replace').strip()
            if e:
                print("  [stderr]", e)
            ssh.close()
        except Exception as ex:
            print(f"  ERROR: {ex}")


if __name__ == '__main__':
    main()
