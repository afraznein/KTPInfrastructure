"""Morning-after check for the .930 activation (2026-08-08, after 03:00 ET).

Covers steps 1-3 of the card's checklist in one pass. Steps 4 (Tier-2 runner
stack re-sync) and 5 (flip the CLAUDE.md row) are deliberate human actions and
are only *unblocked* by this, never performed by it.

Each leg fails loudly rather than quietly:
  * md5 is checked against the pinned .930 hashes on all 24, and the probe
    asserts it saw 48 artifacts -- an empty sweep would otherwise read as
    "0 mismatches".
  * cores are searched in /tmp, NEVER in the game trees: a game-tree search
    matches only core.so/core.ini/core.wav and reads clean whether or not
    anything crashed.
  * [KTP_AUTOBAN] is new in .930 and re-arms bans that were dormant for ~7
    months. A ban of the DATA SERVER or an HLTV proxy is the scenario worth
    waking someone for -- HLStatsX and all 24 proxies share that host, and a
    banned IP cannot rcon in to lift its own ban.
"""
import re
import sys

sys.path.insert(0, r"N:\Nein_\KTP Git Projects")
from ktp_hosts import connect, run, FLEET, PORTS  # noqa: E402

WANT = {"engine_i486.so": "9be1cfd9032a8c0c1f3e4270c66bd173",
        "hlds_linux":     "fbebc79b6fdfb0ebc2081af7c55a155e"}
SENSITIVE = ("74.91.112.242",)          # data server

MD5 = r'''for d in $HOME/dod-*; do p=$(basename "$d" | sed 's/dod-//');
for f in engine_i486.so hlds_linux; do
echo "$p|$f|$(md5sum "$d/serverfiles/$f" 2>/dev/null | cut -d' ' -f1)|$(test -e "$d/serverfiles/$f.new" && echo LEFTOVER || echo -)"; done; done'''

CORES = "find /tmp -maxdepth 1 -name 'core.*' -mtime -1 -printf '%TY-%Tm-%Td %TH:%TM %s %p\\n' 2>/dev/null"
AUTOBAN = r'''grep -h '\[KTP_AUTOBAN\]' $HOME/dod-*/serverfiles/dod/*.log $HOME/dod-*/log/console/*.log 2>/dev/null | tail -40'''

bad, checks, cores, bans = [], 0, [], []
for host in FLEET:
    ssh = connect(host)
    for line in run(ssh, MD5).splitlines():
        parts = line.strip().split("|")
        if len(parts) != 4:
            continue
        port, fname, live, leftover = parts
        checks += 1
        if live != WANT[fname]:
            bad.append("%s:%s %s live=%s" % (host, port, fname, live[:12]))
        if leftover == "LEFTOVER":
            bad.append("%s:%s %s .new NOT consumed" % (host, port, fname))
    for c in run(ssh, CORES).splitlines():
        if c.strip():
            cores.append("%s  %s" % (host, c.strip()))
    for b in run(ssh, AUTOBAN).splitlines():
        if b.strip():
            bans.append("%s  %s" % (host, b.strip()))
    ssh.close()

n = sum(len(PORTS[h]) for h in FLEET) * 2
assert checks == n, "saw %d artifact checks, expected %d -- incomplete sweep, do not trust it" % (checks, n)

print("1. md5 on %d artifacts across 24 instances: %s" % (checks, "24/24 OK" if not bad else "MISMATCH"))
for b in bad:
    print("     !! %s" % b)

print("\n2. cores in /tmp, last 24h: %d" % len(cores))
for c in cores[:10]:
    print("     %s" % c)

print("\n3. [KTP_AUTOBAN] lines: %d" % len(bans))
hot = [b for b in bans if any(ip in b for ip in SENSITIVE)]
for b in bans[-10:]:
    print("     %s" % b)
if hot:
    print("\n   *** %d ban(s) hit the DATA SERVER / HLTV range — review sv_rcon_banpenalty NOW ***"
          % len(hot))

ok = not bad and not cores and not hot
print("\n%s" % ("ACTIVATION CLEAN — steps 4 (Tier-2 stack re-sync) and 5 (flip the CLAUDE.md row "
                "by md5, not banner) are unblocked."
               if ok else "NOT CLEAN — do not re-sync the runner or flip the version row yet."))
print("\nStill owed regardless: the W5 pause/unpause test with real clients, "
      "in the window before tonight's matches.")
sys.exit(0 if ok else 1)
