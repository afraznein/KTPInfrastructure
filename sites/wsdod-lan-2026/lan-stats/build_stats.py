#!/usr/bin/env python3
"""Build the LAN player stats: per day, per map, per player.

Sources are combined by role rather than merged, because they measure different
things and one of them is the league's historical authority:

  HLStatsX (ktp_match_stats + recovered PlayerActions)
      kills, deaths, flags -- the three KTPR terms. Match-scoped, which is what
      the league's existing KTPR and the Everything-v2 sheet are built from, so
      LAN numbers stay comparable to league history.

  HUD (hud_player_stats + hud_damage + hud_prone + hud_spawns)
      assists, damage, hitboxes, prone, class. Everything HLStatsX cannot see.

Where both hold a stat, HLStatsX wins. The HUD counts teamkills and suicides as
kills and logs continuously across half boundaries, so its kill totals run ~11%
higher; taking whichever was larger would silently change what a "kill" means.

KTPR = [ (K/D / avgKD) + (kills_per_half / avgKPH) + 0.25*(flags_per_half / avgFPH) ] / 2.25

The averages are recomputed PER DAY, per the operator's decision: Sunday's field
is thinned by eliminations, so each day is rated against itself. That makes
KTPR internally fair within a day and NOT comparable across days -- the output
carries that warning so nobody sorts one table by it.
"""

from __future__ import annotations

import json
import sys
import warnings
from collections import defaultdict

from lookups import label_classes, label_hitboxes, primary_role, roll_up_roles

import paramiko

warnings.filterwarnings("ignore")

DB = "hlstatsx_lan"
FLAG_COEFF = 0.25
DIVISOR = 1.0 + 1.0 + FLAG_COEFF     # 2.25 -- weights sum, so average == 1.00
MATCH_INDEX = (r"N:/Nein_/KTP Git Projects/KTPAntiCheat/docs/reviews"
               r"/lan-match_index-2026-08-06.csv")


def sid(v: str) -> str:
    """Canonical player key: 'Y:Z', dropping the STEAM_ prefix and the universe
    digit.

    Three formats describe the same player here -- ktp_match_players and
    PlayerUniqueIds store '0:10230748', the HUD stores 'STEAM_0:0:10230748'.
    Left unnormalised they never join, and every player silently splits into two
    entries: one holding kills with no flags, one holding flags with no kills.
    Dropping the universe digit is also correct on its own terms -- STEAM_0:Y:Z
    and STEAM_1:Y:Z are the same account.
    """
    v = (v or "").strip()
    if v.upper().startswith("STEAM_"):
        v = v.split(":", 1)[1] if ":" in v else v
    return v


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("74.91.112.242", username="root", password="g8eSS6k3GH", timeout=25)
    return c


def sql(c, q, t=600):
    cmd = "mysql %s -N --raw -e '%s' 2>&1" % (DB, q.replace("'", "'\\''"))
    _, o, _ = c.exec_command(cmd, timeout=t)
    out = o.read().decode("utf-8", "replace").strip()
    if out.startswith("ERROR"):
        raise RuntimeError(out[:300])
    return [line.split("\t") for line in out.splitlines() if line.strip()]


def roster_roles() -> dict[str, str]:
    """Operator-declared positions. These win over inference.

    A position is a team assignment; a class is only evidence of it. DoD caps
    how many of each class a team can field, so a second Heavy whose STG slot is
    taken spawns as whatever is left and then infers wrong.
    """
    try:
        with open("roster_roles.json", encoding="utf-8") as fh:
            return json.load(fh).get("roles", {})
    except FileNotFoundError:
        return {}


def ktp_matches() -> dict[str, dict]:
    """The .ktp matches only, with their day and map, from the match index."""
    import csv
    out = {}
    with open(MATCH_INDEX, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["type"].strip().lower() != "ktp":
                continue
            day = r["start"][:5]                     # MM-DD
            out[r["match_id"]] = {"map": r["map"], "day": day}
    return out


def main() -> int:
    matches = ktp_matches()
    declared = roster_roles()
    days = sorted({m["day"] for m in matches.values()})
    print("roster overrides: %d" % len(declared))
    print("ktp matches: %d across %s" % (len(matches), ", ".join(days)))

    c = connect()
    ids = ",".join("'%s'" % m for m in matches)

    # --- HLStatsX: the KTPR inputs, per player per match per half -----------
    # half IN (1,2) only: half 0 is the match total and would double everything.
    base = sql(c, """
        SELECT s.match_id, s.half, p.steam_id, p.player_name,
               s.kills, s.deaths, s.headshots, s.damage, s.score
        FROM ktp_match_stats s
        JOIN ktp_match_players p
          ON p.match_id = s.match_id AND p.player_id = s.player_id
        WHERE s.half IN (1,2) AND s.match_id IN (%s)""" % ids)
    print("hlstatsx rows: %d" % len(base))

    # --- recovered captures, per player per match per half ------------------
    caps = sql(c, """
        SELECT e.match_id, u.uniqueId, COUNT(*)
        FROM hlstats_Events_PlayerActions e
        JOIN hlstats_PlayerUniqueIds u ON u.playerId = e.playerId
        WHERE e.actionId IN (337,338) AND e.match_id IN (%s)
        GROUP BY e.match_id, u.uniqueId""" % ids)
    cap_by = {(m, sid(uid)): int(n) for m, uid, n in caps}
    print("capture groups: %d" % len(cap_by))

    # --- HUD: everything HLStatsX cannot provide ---------------------------
    hud = sql(c, """
        SELECT match_id, steam_id,
               SUM(assists), SUM(damage), SUM(hits), SUM(hs_hits),
               SUM(caps), SUM(cap_breaks), SUM(obj_score), MAX(best_streak),
               SUM(nade_kills), SUM(gun_kills)
        FROM hud_player_stats
        WHERE is_final = 1 AND match_id IN (%s)
        GROUP BY match_id, steam_id""" % ids)
    hud_by = {(m, sid(s)): [int(x or 0) for x in rest] for m, s, *rest in hud}
    print("hud player-match rows: %d" % len(hud_by))

    prone = sql(c, "SELECT match_id, steam_id, COUNT(*) FROM hud_prone "
                   "WHERE match_id IN (%s) GROUP BY match_id, steam_id" % ids)
    prone_by = {(m, sid(s)): int(n) for m, s, n in prone}

    classes = sql(c, "SELECT match_id, steam_id, class_id, COUNT(*) FROM hud_spawns "
                     "WHERE match_id IN (%s) GROUP BY match_id, steam_id, class_id" % ids)
    class_by: dict[tuple, dict] = defaultdict(dict)
    for m, s, cls, n in classes:
        class_by[(m, sid(s))][cls] = int(n)

    hitbox = sql(c, "SELECT attacker_id, hitplace, COUNT(*), SUM(damage) FROM hud_damage "
                    "WHERE match_id IN (%s) AND attacker_id IS NOT NULL "
                    "GROUP BY attacker_id, hitplace" % ids)
    hb_by: dict[str, dict] = defaultdict(dict)
    for s, place, n, dmg in hitbox:
        hb_by[sid(s)][place or "unknown"] = {"hits": int(n), "damage": int(dmg or 0)}
    c.close()

    # --- fold into (day, map, player) and (day, player) ---------------------
    def blank():
        return {"halves": 0, "kills": 0, "deaths": 0, "headshots": 0, "damage_hl": 0,
                "score": 0, "flags": 0, "assists": 0, "damage_hud": 0, "hits": 0,
                "hs_hits": 0, "caps_hud": 0, "cap_breaks": 0, "obj_score": 0,
                "best_streak": 0, "nade_kills": 0, "gun_kills": 0, "prone": 0,
                "matches": set(), "classes": defaultdict(int), "name": ""}

    per_map: dict[tuple, dict] = defaultdict(blank)
    per_day: dict[tuple, dict] = defaultdict(blank)
    seen_hud: set = set()

    for mid, half, steam_raw, name, k, d, hs, dmg, sc in base:
        steam = sid(steam_raw)
        meta = matches.get(mid)
        if not meta:
            continue
        for bucket, key in ((per_map, (meta["day"], meta["map"], steam)),
                            (per_day, (meta["day"], steam))):
            b = bucket[key]
            b["name"] = name or b["name"]
            b["halves"] += 1
            b["kills"] += int(k or 0)
            b["deaths"] += int(d or 0)
            b["headshots"] += int(hs or 0)
            b["damage_hl"] += int(dmg or 0)
            b["score"] += int(sc or 0)
            b["matches"].add(mid)

    for (mid, steam), n in cap_by.items():
        meta = matches.get(mid)
        if not meta:
            continue
        per_map[(meta["day"], meta["map"], steam)]["flags"] += n
        per_day[(meta["day"], steam)]["flags"] += n

    HUDF = ["assists", "damage_hud", "hits", "hs_hits", "caps_hud", "cap_breaks",
            "obj_score", "best_streak", "nade_kills", "gun_kills"]
    for (mid, steam), vals in hud_by.items():
        meta = matches.get(mid)
        if not meta:
            continue
        seen_hud.add(steam)
        for bucket, key in ((per_map, (meta["day"], meta["map"], steam)),
                            (per_day, (meta["day"], steam))):
            b = bucket[key]
            for f, v in zip(HUDF, vals):
                b[f] = max(b[f], v) if f == "best_streak" else b[f] + v
        n = prone_by.get((mid, steam), 0)
        if n:
            per_map[(meta["day"], meta["map"], steam)]["prone"] += n
            per_day[(meta["day"], steam)]["prone"] += n
        for cls, n in class_by.get((mid, steam), {}).items():
            per_map[(meta["day"], meta["map"], steam)]["classes"][cls] += n
            per_day[(meta["day"], steam)]["classes"][cls] += n

    print("players with hud data: %d" % len(seen_hud))

    # --- KTPR, with averages recomputed per day ----------------------------
    def rates(b):
        halves = b["halves"] or 1
        kd = b["kills"] / b["deaths"] if b["deaths"] else float(b["kills"])
        return kd, b["kills"] / halves, b["flags"] / halves

    report = {"generated_for": "Philly LAN 2026", "days": {}, "coefficients": {
        "flag": FLAG_COEFF, "divisor": DIVISOR,
        "note": "Averages recomputed per day; KTPR is not comparable across days."}}

    for day in days:
        rows = {k: v for k, v in per_day.items() if k[0] == day}
        # A player with one half of data distorts an average badly; require two.
        pool = [rates(v) for v in rows.values() if v["halves"] >= 2 and v["deaths"] > 0]
        if not pool:
            continue
        avg_kd = sum(p[0] for p in pool) / len(pool)
        avg_kph = sum(p[1] for p in pool) / len(pool)
        avg_fph = sum(p[2] for p in pool) / len(pool) or 1e-9

        players = []
        for (_, steam), b in rows.items():
            kd, kph, fph = rates(b)
            ktpr = ((kd / avg_kd) + (kph / avg_kph)
                    + FLAG_COEFF * (fph / avg_fph)) / DIVISOR
            players.append({
                "steam_id": steam, "name": b["name"],
                "ktpr": round(ktpr, 3),
                "matches": len(b["matches"]), "halves": b["halves"],
                "kills": b["kills"], "deaths": b["deaths"],
                "kd": round(kd, 3), "kills_per_half": round(kph, 2),
                "flags": b["flags"], "flags_per_half": round(fph, 2),
                "headshots": b["headshots"], "score": b["score"],
                "damage_hlstatsx": b["damage_hl"],
                # HUD-only fields below
                "assists": b["assists"], "damage_hud": b["damage_hud"],
                "hits": b["hits"], "hs_hits": b["hs_hits"],
                "caps_hud": b["caps_hud"], "cap_breaks": b["cap_breaks"],
                "obj_score": b["obj_score"], "best_streak": b["best_streak"],
                "nade_kills": b["nade_kills"], "gun_kills": b["gun_kills"],
                "prone_changes": b["prone"],
                "classes": label_classes(b["classes"]),
                "roles": roll_up_roles(b["classes"]),
                "primary_role": declared.get(steam) or primary_role(b["classes"]),
                "role_source": "roster" if steam in declared else "inferred",
                "hitboxes": label_hitboxes(hb_by.get(steam, {})),
            })
        players.sort(key=lambda p: -p["ktpr"])
        report["days"][day] = {
            "averages": {"kd": round(avg_kd, 4), "kills_per_half": round(avg_kph, 4),
                         "flags_per_half": round(avg_fph, 4), "pool": len(pool)},
            "players": players,
            "maps": {},
        }
        print("\n%s -- avg K/D %.3f, kills/half %.2f, flags/half %.2f (pool %d)"
              % (day, avg_kd, avg_kph, avg_fph, len(pool)))
        for p in players[:5]:
            print("   %-22s KTPR %.3f  %2dm  K/D %.2f  kph %.1f  fph %.2f  asst %d"
                  % (p["name"][:22], p["ktpr"], p["matches"], p["kd"],
                     p["kills_per_half"], p["flags_per_half"], p["assists"]))

    # --- per map, using that day's averages so maps stay comparable --------
    for (day, mp, steam), b in per_map.items():
        d = report["days"].get(day)
        if not d:
            continue
        a = d["averages"]
        kd, kph, fph = rates(b)
        ktpr = ((kd / a["kd"]) + (kph / a["kills_per_half"])
                + FLAG_COEFF * (fph / (a["flags_per_half"] or 1e-9))) / DIVISOR
        d["maps"].setdefault(mp, []).append({
            "steam_id": steam, "name": b["name"], "ktpr": round(ktpr, 3),
            "matches": len(b["matches"]), "halves": b["halves"],
            "kills": b["kills"], "deaths": b["deaths"], "kd": round(kd, 3),
            "flags": b["flags"], "damage_hlstatsx": b["damage_hl"],
            "assists": b["assists"],
            "damage_hud": b["damage_hud"], "prone_changes": b["prone"],
        })
    for d in report["days"].values():
        for mp in d["maps"]:
            d["maps"][mp].sort(key=lambda p: -p["ktpr"])

    out = "lan-stats.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print("\nwrote %s" % out)
    for day, d in report["days"].items():
        print("  %s: %d players, %d maps" % (day, len(d["players"]), len(d["maps"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
