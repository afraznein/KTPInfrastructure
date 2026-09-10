"""Build player_id (hlstatsx) -> season -> division, using the website pull
in data/website/*.json plus hlstats_PlayerUniqueIds for the identity bridge.

Two different player_id spaces meet here: the website's own ktp.player.id
(used by legacy_player_season, season_team_member, player_steam) and
hlstatsx's player_id (used by everything else in this project). steam_id64
is the only key that bridges them.

S1-S9: legacy_player_season already carries steam_id64 directly (a generated
column on the website side that ignores the universe digit -- see SCHEMA.md).
S10 (and beyond): season_team_member -> player_steam for steam_id64.

hlstats_PlayerUniqueIds stores "authserver:accountid" (no universe prefix,
no leading 76561197960265728 offset) -- convert steam_id64 to that form with
the standard SteamID64 formula and match on it.
"""
import json
from pathlib import Path

DATA = Path(__file__).parent / "data"
STEAM64_BASE = 76561197960265728


def steam64_to_hlstats(steam_id64: str) -> str:
    n = int(steam_id64) - STEAM64_BASE
    auth = n % 2
    account = n // 2
    return f"{auth}:{account}"


def load_hlstats_bridge():
    out = {}
    for line in open(DATA / "hlstats_player_unique_ids.tsv", encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 2 or parts[1] == "uniqueId":
            continue
        pid, unique = parts
        out[unique] = int(pid)
    return out


def load_json(name):
    return json.loads((DATA / "website" / f"{name}.json").read_text(encoding="utf-8"))


def build():
    bridge = load_hlstats_bridge()
    seasons = {s["id"]: s["number"] for s in load_json("season")}
    divisions = {d["id"]: d["name"] for d in load_json("division")}
    legacy_team_by_id = {t["id"]: t for t in load_json("legacy_season_team")}

    website_steam = {p["player_id"]: p["steam_id64"] for p in load_json("player_steam") if p["status"] == "current"}

    history = {}  # hlstats_player_id -> [{season, division, source}]
    unmatched = 0

    # S1-S9: steam_id64 is directly on legacy_player_season; division comes
    # from the linked legacy_season_team (None for unattributed stints).
    for row in load_json("legacy_player_season"):
        steam64 = row.get("steam_id64")
        if not steam64:
            continue
        hlstats_key = steam64_to_hlstats(steam64)
        pid = bridge.get(hlstats_key)
        if pid is None:
            unmatched += 1
            continue
        season_num = seasons.get(row["season_id"])
        team = legacy_team_by_id.get(row["legacy_season_team_id"])
        div_name = team["division"] if team else None
        history.setdefault(pid, []).append(dict(season=season_num, division=div_name, source="legacy"))

    # S10+: season_team_member -> season_team -> division, player -> player_steam -> steam_id64.
    season_team_lookup = {t["id"]: t for t in load_json("season_team")}
    for row in load_json("season_team_member"):
        st = season_team_lookup.get(row["season_team_id"])
        if not st:
            continue
        steam64 = website_steam.get(row["player_id"])
        if not steam64:
            continue
        hlstats_key = steam64_to_hlstats(steam64)
        pid = bridge.get(hlstats_key)
        if pid is None:
            unmatched += 1
            continue
        season_num = seasons.get(st["season_id"])
        div_name = divisions.get(st["division_id"])
        history.setdefault(pid, []).append(dict(season=season_num, division=div_name, source="season_team_member"))

    print(f"{len(history)} hlstatsx players matched to at least one season; {unmatched} rows unmatched (no hlstats play record)")
    Path(__file__).with_name("division_history.json").write_text(json.dumps(history, indent=1), encoding="utf-8")
    return history


if __name__ == "__main__":
    h = build()
    for pid in (168, 119):  # the two S9 sandbagging candidates flagged earlier
        print(pid, sorted(h.get(pid, []), key=lambda r: (r["season"] or 0)))
