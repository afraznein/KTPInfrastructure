#!/usr/bin/env python3
"""Build demos/LAN-PHILLY2026/<type>/ to EXACTLY one intended set of hardlinks.

Idempotent and total: it computes the full desired filename set for a match type, then
makes the directory equal that set -- creating what is missing and deleting what is not
wanted. Earlier passes patched incrementally and left the directory holding both the old
and new names for the same demo, which is how ktp ended up at 248 files for 114 demos.

Naming
  resolved match (both sides map to a known clan tag):
      <type>_<match_id>_h<n>_<team1>_<team2>_<map>[_partN].dem
  unresolved match (a side has <3 players sharing a known tag):
      <type>_<match_id>-LAN<n>_<h1|h2>-<hltv_ts>-<map>[_partN].dem   (server-named)

Halves are assigned by OVERLAP with the half window, not by start instant: HLTV rotates on
its own ~20-minute cadence, so a file routinely opens 1-3 minutes before a half goes live
and then runs 20 minutes into it. Demos recorded entirely outside the match window are
trailing footage and are not published.
"""
import argparse, collections, csv, json, os, re, subprocess

AR = "/opt/ktp-lan-archive/philly-2026"
SRC = AR + "/demos"
ROOT = "/home/hltvserver/hlds/dod/demos/LAN-PHILLY2026"

TAG_TEAM = {
    "NoSo": "NoSoul", "[$]": "Price is Right", "dicE[: :]": "dicE", "iH.": "IcyHot",
    "[NATO]": "NATO", "uR[TM]": "Uncle Rico's TM", "ßℓυ†н |": "Arrested Development",
    "вℓυтн |": "Arrested Development", "BLUTH |": "Arrested Development",
    "[bb]": "Best Buds", "****JTM": "onLAN thunder", "b.": "b Team",
    "DAYMAN": "DAYMAN", "VPN": "VPN", "[team9]": "team9",
}

def slug(n):
    return "".join(re.findall(r"[A-Za-z0-9]+", n)) or "Unknown"

def tag_of(n):
    n = n.strip()
    for p in (r"^(\[[^\]]+\])", r"^([A-Za-z0-9_.\-]+\[[^\]]*\])", r"^(\*{2,}[A-Za-z]+)",
              r"^([^\s|]+\s*\|)", r"^([A-Za-z]+\.)"):
        m = re.match(p, n)
        if m:
            return m.group(1).strip()
    m = re.match(r"^(\S{1,10}?)[\s.]", n)
    return m.group(1) if m else n[:8]

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
ap.add_argument("--type", default="all")
args = ap.parse_args()

windows = {m["id"]: m for m in json.load(open(AR + "/match_windows.json"))}
parsed = {d["name"]: d for d in json.load(open(AR + "/demos_parsed.json"))}
allrows = list(csv.DictReader(open(AR + "/match_index.csv")))
TYPES = ["ktp", "scrim", "draft", "12man"] if args.type == "all" else [args.type]

# rosters once, for every match
ids = [r["match_id"] for r in allrows]
q = ("SELECT match_id, team, player_name FROM ktp_match_players WHERE match_id IN (%s)"
     % ",".join("'" + m + "'" for m in ids))
mysql = subprocess.run(["mysql", "-N", "-B", "hlstatsx_lan", "-e", q],
                       capture_output=True, text=True)
# No roster means every match resolves to "unresolved", and --apply then os.removes
# the correctly-named hardlinks and rebuilds the tree under server-named form. A
# failed query has to stop the run, not quietly change the answer.
if mysql.returncode != 0 or not mysql.stdout.strip():
    raise SystemExit("roster query failed (rc=%d): %s"
                     % (mysql.returncode, mysql.stderr.strip()[:400] or "no rows"))
out = mysql.stdout
side = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
for ln in out.split("\n"):
    p = ln.split("\t")
    if len(p) == 3:
        side[p[0]][p[1]][tag_of(p[2])] += 1

grand = {}
for MT in TYPES:
    rows = [r for r in allrows if r["type"] == MT]
    want = {}                      # filename -> source path
    resolved = unresolved = outside = 0
    for r in rows:
        mid = r["match_id"]
        w = windows.get(mid, {}) or {}
        hv = w.get("halves") or {}
        h1s, h2s, close = hv.get("h1"), hv.get("h2"), w.get("close")

        named = {}
        for s in ("1", "2"):
            c = side.get(mid, {}).get(s)
            if not c:
                continue
            tg, n = c.most_common(1)[0]
            if n >= 3 and tg in TAG_TEAM:
                named[s] = TAG_TEAM[tg]
        team_mode = len(named) == 2
        if team_mode: resolved += 1
        else: unresolved += 1

        demos = sorted([x for x in (r["demo_files"] or "").split(";") if x],
                       key=lambda n: parsed.get(n, {}).get("start", 0))
        per = collections.Counter()
        for name in demos:
            info = parsed.get(name)
            if not info or not os.path.exists(os.path.join(SRC, name)):
                continue
            end = close or info["end"]
            if h1s and h2s:
                o1 = max(0, min(info["end"], h2s) - max(info["start"], h1s))
                o2 = max(0, min(info["end"], end) - max(info["start"], h2s))
                if o1 == 0 and o2 == 0:
                    outside += 1
                    continue
                half = "h2" if o2 > o1 else "h1"
            else:
                half = "h1"
            per[half] += 1
            part = "" if per[half] == 1 else "_part%d" % per[half]
            m = re.match(r"auto_lan(\d+)-(\d{10})-(.+)\.dem$", name)
            lan, ts, mapname = (m.group(1), m.group(2), m.group(3)) if m else ("0", "0", r["map"])
            if team_mode:
                fn = "%s_%s_%s_%s_%s_%s%s.dem" % (MT, mid, half, slug(named["1"]),
                                                  slug(named["2"]), mapname, part)
            else:
                fn = "%s_%s-LAN%s_%s-%s-%s%s.dem" % (MT, mid, lan, half, ts, mapname, part)
            want[fn] = os.path.join(SRC, name)

    dest = os.path.join(ROOT, MT)
    os.makedirs(dest, exist_ok=True)
    have = {f for f in os.listdir(dest) if f.endswith(".dem")}
    add, rm = set(want) - have, have - set(want)
    grand[MT] = (len(want), len(add), len(rm), resolved, unresolved, outside)
    print("%-6s want=%-4d add=%-4d remove=%-4d | matches resolved=%-3d unresolved=%-2d | outside-window demos skipped=%d"
          % (MT, len(want), len(add), len(rm), resolved, unresolved, outside))
    if args.apply:
        for f in rm:
            os.remove(os.path.join(dest, f))
        for f in add:
            os.link(want[f], os.path.join(dest, f))
        now = {x for x in os.listdir(dest) if x.endswith(".dem")}
        assert now == set(want), "dir does not equal intended set"
        print("        -> now %d files, exactly the intended set" % len(now))

if not args.apply:
    print("\nDRY RUN — nothing changed.")
