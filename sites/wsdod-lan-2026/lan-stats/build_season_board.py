#!/usr/bin/env python3
"""Per-view KTPR boards for the WSDoD page, using the current `team` formula.

One formula, three views. Saturday, Sunday and the full weekend are each scored
by the real engine (docs/ktpr_mcp/ktpr_engine.py, [profiles.new]) rather than a
fourth reimplementation of KTPR — the site and the MCP tool disagreeing about
what KTPR means is the failure this avoids. Each view is rated against its own
field: the per-day views derive their baselines from that day's players alone
(the operator's ruling stands — Sunday's field is thinned by eliminations, so a
day is rated against itself), the weekend view from combined weekend totals.
Same formula everywhere; only the baseline population changes between views.
This replaced the legacy additive day formula on 2026-08-09 — the day boards
and the weekend board now answer to one definition of KTPR.

team_placement_weight is forced to 0 here. The engine's live profile multiplies
each player by their team's FINAL tournament finish, which would bake the result
into a rating the page presents as individual performance — and the awards it
feeds are per-stage.

Per-map boards are scored against the DAY's baselines (per-map tables have
always used the day's field) with tw_break forced to 0: lan-stats.json records
no per-map capture breaks, and scoring invented zeros would penalize players
unevenly. Dropping the term renormalizes the weights, which is exact — a
five-term KTPR, labelled as such on the page.

    python build_season_board.py            # -> season-board.json
    python build_season_board.py --check    # exit 1 if the board is stale
"""
import collections
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "..", "docs", "ktpr_mcp"))
sys.path.insert(0, ENGINE_DIR)

from ktpr_engine import (Player, load_params, compute_team, classify_styles,  # noqa: E402
                         _team_baselines)

STATS = os.path.join(HERE, "lan-stats.json")
TEAMS = os.path.join(HERE, "player_teams.json")
OUT = os.path.join(HERE, "season-board.json")

# "3rd" is the league's own position name; the engine's vocabulary calls that
# bucket SMG. Translate on the way in so a future non-neutral role_weight can't
# silently miss it, and keep the league's name for display.
ROLE_ALIASES = {"3rd": "SMG"}
ROLE_DISPLAY = {"SMG": "3rd"}

DAY_LABELS = {"08-01": "Saturday", "08-02": "Sunday"}


def make_player(name, matches, halves, kills, deaths, flags, assists, damage,
                breaks, role, team) -> Player:
    halves = halves or 1
    return Player(
        name=name, matches=matches,
        kd_ratio=(kills / deaths) if deaths else float(kills),
        kills_half=kills / halves, deaths_half=deaths / halves,
        flags_half=flags / halves, assists_half=assists / halves,
        damage_half=damage / halves, breaks_half=breaks / halves,
        role=ROLE_ALIASES.get(role, role), team=team)


def baseline_meta(players: list, params) -> dict:
    """Who actually sets this view's baselines: the regulars, counted per role.
    Roles below class_min_size fall back to the global median — the page says
    which population a view is rated against, so that fact is emitted too."""
    thr = max(params.part_floor,
              max((pl.matches for pl in players), default=0.0) * 0.66)
    regs = [pl for pl in players if pl.matches >= thr] or players
    by_role = collections.Counter(pl.role for pl in regs)
    return {
        "pool": len(players),
        "regulars": len(regs),
        "role_regulars": {ROLE_DISPLAY.get(r, r): n
                          for r, n in sorted(by_role.items())},
        "own_baseline_roles": sorted(ROLE_DISPLAY.get(r, r)
                                     for r, n in by_role.items()
                                     if n >= params.class_min_size),
    }


def view_rows(players, params, extras) -> list:
    """Score one view's Player list and shape the output rows. `extras` carries
    per-player fields the engine doesn't know (steam_id, counts, day names)."""
    vals = compute_team(players, params, None)
    styles = classify_styles(players, params)
    rows = []
    for pl, v, st, ex in zip(players, vals, styles, extras):
        if v is None:
            continue
        rows.append(dict({
            "steam_id": ex["steam_id"], "name": pl.name, "team": pl.team,
            "position": ROLE_DISPLAY.get(pl.role, pl.role), "role": pl.role,
            "role_source": ex["role_source"],
            "ktpr": round(v, 3), "style": st,
            "matches": ex["matches"], "halves": ex["halves"],
            "kd": round(pl.kd_ratio, 3),
            "kills_per_half": round(pl.kills_half, 2),
            "deaths_per_half": round(pl.deaths_half, 2),
            "assists_per_half": round(pl.assists_half, 2),
            "damage_per_half": round(pl.damage_half, 1),
            "flags_per_half": round(pl.flags_half, 2),
            "breaks_per_half": round(pl.breaks_half, 3),
        }, **ex.get("more", {})))
    rows.sort(key=lambda r: -r["ktpr"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def day_view(stats, teams, day_key, params):
    players, extras = [], []
    for p in stats["days"][day_key]["players"]:
        players.append(make_player(
            p["name"], p["matches"], p["halves"], p["kills"], p["deaths"],
            p["flags"], p["assists"], p["damage_hlstatsx"], p["cap_breaks"],
            p.get("primary_role") or "?",
            (teams.get(p["steam_id"]) or {}).get("team", "?")))
        extras.append({"steam_id": p["steam_id"],
                       "role_source": p.get("role_source") or "inferred",
                       "matches": p["matches"], "halves": p["halves"]})
    return players, extras


def weekend_view(stats, teams, params):
    totals = collections.defaultdict(collections.Counter)
    role, name, role_src = {}, {}, {}
    day_names = collections.defaultdict(dict)
    for day, dd in stats["days"].items():
        for p in dd["players"]:
            sid = p["steam_id"]
            name[sid] = p["name"]
            day_names[sid][day] = p["name"]
            role[sid] = p.get("primary_role") or "?"
            if role_src.get(sid) != "roster":
                role_src[sid] = p.get("role_source") or "inferred"
            # damage_hlstatsx, not damage_hud: the match record logs damage
            # (half 1+2 only), so the rating shouldn't take the HUD's
            # warmup-tainted copy of a stat the record already has.
            for k in ("matches", "halves", "kills", "deaths", "flags",
                      "assists", "damage_hlstatsx", "cap_breaks"):
                totals[sid][k] += p.get(k) or 0

    players, extras = [], []
    for sid in sorted(totals):
        t = totals[sid]
        players.append(make_player(
            name[sid], t["matches"], t["halves"], t["kills"], t["deaths"],
            t["flags"], t["assists"], t["damage_hlstatsx"], t["cap_breaks"],
            role[sid], (teams.get(sid) or {}).get("team", "?")))
        extras.append({"steam_id": sid, "role_source": role_src[sid],
                       "matches": t["matches"], "halves": t["halves"],
                       "more": {"days": sorted(day_names[sid]),
                                "names_by_day": day_names[sid]}})
    return players, extras


def map_boards(stats, teams, day_key, day_players, params):
    """name -> KTPR per map, scored against the day's baselines, breaks term
    dropped (no per-map break counts exist — see module docstring)."""
    p_map = copy.deepcopy(params)
    p_map.tw_break = 0.0
    baseline_for = _team_baselines(day_players, params)
    role_by_sid = {p["steam_id"]: p.get("primary_role") or "?"
                   for p in stats["days"][day_key]["players"]}
    out = {}
    for mp, rows in stats["days"][day_key]["maps"].items():
        pls = [make_player(
            r["name"], r["matches"], r["halves"], r["kills"], r["deaths"],
            r["flags"], r["assists"], r["damage_hlstatsx"], 0,
            role_by_sid.get(r["steam_id"], "?"),
            (teams.get(r["steam_id"]) or {}).get("team", "?")) for r in rows]
        vals = compute_team(pls, p_map, baseline_for)
        out[mp] = {r["name"]: round(v, 3)
                   for r, v in zip(rows, vals) if v is not None}
    return out


def build() -> dict:
    stats = json.load(open(STATS, encoding="utf-8"))
    teams = json.load(open(TEAMS, encoding="utf-8"))

    params = copy.deepcopy(load_params("new", os.path.join(ENGINE_DIR, "weights.toml")))
    params.team_placement_weight = 0.0

    views, map_ktpr = {}, {}
    for day_key in sorted(stats["days"]):
        players, extras = day_view(stats, teams, day_key, params)
        views[day_key] = {
            "label": DAY_LABELS.get(day_key, day_key),
            "baseline": baseline_meta(players, params),
            "players": view_rows(players, params, extras),
        }
        map_ktpr[day_key] = map_boards(stats, teams, day_key, players, params)

    players, extras = weekend_view(stats, teams, params)
    views["weekend"] = {
        "label": "Full weekend",
        "baseline": baseline_meta(players, params),
        "players": view_rows(players, params, extras),
    }

    # The page prints the formula from these, so every number shown to a reader
    # is the one the engine ran — a weight transcribed into prose would rot.
    knobs = {k: getattr(params, k) for k in
             ("scale", "kill_exp", "tw_kill", "tw_kd", "tw_assist", "tw_damage",
              "tw_flag", "tw_break", "break_smooth_k", "dmg_interaction",
              "assist_interaction", "dmg_scale_min", "dmg_scale_max",
              "death_w", "death_cap", "team_death_up_cap", "death_kill_relief",
              "ratio_cap", "ratio_floor", "team_placement_weight")}
    knobs["tw_sum"] = round(params.tw_kill + params.tw_kd + params.tw_assist
                            + params.tw_damage + params.tw_flag + params.tw_break, 4)

    return {
        "_source": [
            "KTPR boards for the WSDoD page, computed by docs/ktpr_mcp/ktpr_engine.py",
            "([profiles.new], the team formula). Generated by build_season_board.py --",
            "do not hand-edit.",
            "Three views, one formula: the per-day views are rated against that day's",
            "own field (per-day medians), the weekend view against combined totals.",
            "Numbers compare within a view, not across views.",
            "team_placement_weight is forced to 0: the live profile boosts players by",
            "their team's final finish, which does not belong in a rating the page",
            "presents as individual performance.",
            "map_ktpr scores each per-map table against the day's baselines with the",
            "breaks term dropped (tw_break=0, weights renormalized) -- lan-stats.json",
            "records no per-map capture breaks.",
            "Damage is HLStatsX (ktp_match_stats, halves 1+2). Assists and capture",
            "breaks are the only HUD-sourced inputs -- the match record doesn't log",
            "them yet.",
        ],
        "generated_for": stats.get("generated_for"),
        "formula": "team", "profile": "new", "knobs": knobs,
        "views": views,
        "map_ktpr": map_ktpr,
    }


def main() -> int:
    # player names carry full-width unicode a cp1252 console can't print
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    board = build()
    text = json.dumps(board, ensure_ascii=False, indent=1)
    if "--check" in sys.argv:
        cur = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if cur.strip() != text.strip():
            print("season-board.json is STALE — re-run build_season_board.py")
            return 1
        print("season-board.json is current")
        return 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
    for key, view in board["views"].items():
        rows = view["players"]
        b = view["baseline"]
        print(f"{view['label']} ({key}): {len(rows)} players, "
              f"{b['regulars']} regulars set the baselines "
              f"{b['role_regulars']}")
        for r in rows[:5]:
            print(f"  {r['rank']:>2}. {r['name'][:26]:<26} {r['team'][:22]:<22} "
                  f"{r['ktpr']:.3f}  {r['style']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
