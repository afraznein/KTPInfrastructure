#!/usr/bin/env python3
"""Prepare aggregate-only Anzio spatial atlas data from local Lane B fixtures.

The output deliberately contains no player names, player identifiers, Steam IDs,
or per-player tracks.  It is an intermediate rendering payload made exclusively
from aggregate grid cells, aggregate vectors, and aggregate summary rows.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DEFAULT_MAP_CONFIG = REPO / "config/analytics/spatial_maps/dod_anzio.json"


def configure_map(path: Path) -> dict:
    """Load the reviewed map geometry and analytical windows."""
    global MAP_CONFIG, MAP_NAME, GRID, SAMPLE_SECONDS, OBJECTIVE_RADIUS
    global NEAREST_SAMPLE_SECONDS, ISOLATION_RADIUS, TRADE_SECONDS
    global MULTIKILL_SECONDS, OPENING_SECONDS, EVENT_WINDOW_SECONDS
    global TARGET_CELL_MINIMUM_SECONDS, CORPUS_CELL_MINIMUM_SECONDS
    global RECURRING_LANE_MINIMUM, FLAGS, FLAG_BY_CODE
    config = json.loads(path.read_text(encoding="utf-8"))
    analysis = config["analysis"]
    MAP_CONFIG = config
    MAP_NAME = str(config["map_name"])
    GRID = float(analysis["grid_size_units"])
    SAMPLE_SECONDS = float(analysis["sample_seconds"])
    OBJECTIVE_RADIUS = float(analysis["objective_radius_units"])
    NEAREST_SAMPLE_SECONDS = float(analysis["nearest_sample_seconds"])
    ISOLATION_RADIUS = float(analysis["isolation_radius_units"])
    TRADE_SECONDS = float(analysis["trade_seconds"])
    MULTIKILL_SECONDS = float(analysis["multikill_seconds"])
    OPENING_SECONDS = float(analysis["opening_seconds"])
    EVENT_WINDOW_SECONDS = float(analysis["event_window_seconds"])
    TARGET_CELL_MINIMUM_SECONDS = float(analysis["target_cell_minimum_seconds"])
    CORPUS_CELL_MINIMUM_SECONDS = float(analysis["corpus_cell_minimum_seconds"])
    RECURRING_LANE_MINIMUM = int(analysis["recurring_lane_minimum"])
    FLAGS = list(config["flags"])
    FLAG_BY_CODE = {flag["code"]: flag for flag in FLAGS}
    return config


configure_map(DEFAULT_MAP_CONFIG)

WANTED_TABLES = {
    "hlstats_Actions",
    "hlstats_Events_Frags",
    "hlstats_Events_PlayerActions",
    "ktp_damage_events",
    "ktp_flag_captures",
    "ktp_match_players",
    "ktp_matches",
    "ktp_position_samples",
}


def dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def number(value, default=0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


def integer(value, default=0) -> int:
    if value is None or value == "":
        return default
    return int(value)


def parse_sql(path: Path) -> dict[str, list[dict]]:
    tables: dict[str, list[dict]] = defaultdict(list)
    insert_re = re.compile(r"^INSERT INTO `([^`]+)` \((.*?)\) VALUES \((.*)\);$")
    opener = gzip.open if path.suffix == ".gz" else Path.open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = insert_re.match(line.rstrip("\r\n"))
            if not match or match.group(1) not in WANTED_TABLES:
                continue
            table, columns_text, tuple_text = match.groups()
            columns = [part.strip().strip("`") for part in columns_text.split(",")]
            values = next(csv.reader([tuple_text], delimiter=",", quotechar="'", escapechar="\\"))
            if len(columns) != len(values):
                raise ValueError(f"{path}: {table} column/value mismatch: {len(columns)} != {len(values)}")
            row = {}
            for key, value in zip(columns, values):
                value = value.strip()
                row[key] = None if value.upper() == "NULL" else value
            tables[table].append(row)
    return tables


def cell_key(x: float, y: float) -> str:
    return f"{math.floor(x / GRID)},{math.floor(y / GRID)}"


def cell_center(key: str) -> tuple[float, float]:
    x, y = (int(part) for part in key.split(","))
    return ((x + 0.5) * GRID, (y + 0.5) * GRID)


def distance(x1, y1, x2, y2) -> float:
    return math.hypot(x2 - x1, y2 - y1)


def weapon_group(weapon: str) -> str:
    weapon = (weapon or "unknown").lower()
    groups = {
        "rifle": {"garand", "k43", "kar", "m1carbine", "enfield", "fg42"},
        "automatic": {"bar", "mp40", "mp44", "stg44", "thompson", "greasegun", "mp34"},
        "machine-gun": {"30cal", "mg34", "mg42", "bren"},
        "sniper": {"scopedkar", "spring", "scopedenfield", "scoped_fg42"},
        "explosive": {"grenade", "grenade2", "bazooka", "pschreck", "mortar", "riflegren_us", "riflegren_ger"},
        "sidearm-melee": {"colt", "luger", "webley", "knife", "spade", "amerknife", "bayonet"},
    }
    for group, weapons in groups.items():
        if weapon in weapons:
            return group
    return "other"


def aggregate_cells(events, point="killer", weight=1.0) -> Counter:
    cells = Counter()
    for event in events:
        x = event.get(f"{point}_x") if point in {"killer", "victim"} else event.get("x")
        y = event.get(f"{point}_y") if point in {"killer", "victim"} else event.get("y")
        if x is not None and y is not None:
            cells[cell_key(x, y)] += weight if not callable(weight) else weight(event)
    return cells


def cells_payload(values: dict, scale=1.0) -> list[dict]:
    return [{"key": key, "value": round(float(value) * scale, 6)} for key, value in sorted(values.items()) if value != 0]


def rate_cells(events: Counter, occupancy_seconds: Counter, minimum_seconds: float) -> dict:
    return {
        key: 60.0 * events.get(key, 0.0) / seconds
        for key, seconds in occupancy_seconds.items()
        if seconds >= minimum_seconds
    }


def signed_delta(left: dict, right: dict, required_left=None, required_right=None) -> dict:
    keys = set(left) | set(right)
    result = {}
    for key in keys:
        if required_left is not None and key not in required_left:
            continue
        if required_right is not None and key not in required_right:
            continue
        value = left.get(key, 0.0) - right.get(key, 0.0)
        if value:
            result[key] = value
    return result


def nearest_position(match, player_id: int, when: datetime, max_seconds=NEAREST_SAMPLE_SECONDS):
    best, best_delta = None, max_seconds + 0.001
    for sample in match["positions_by_player"].get(player_id, []):
        delta = abs((sample["time"] - when).total_seconds())
        if delta < best_delta:
            best, best_delta = sample, delta
    return best


def unique_capture_events(captures):
    events = {}
    for row in captures:
        key = (row["half"], row["flag"], row["time"])
        events.setdefault(key, row)
    return sorted(events.values(), key=lambda item: item["time"])


def reconstruct_capouts(match):
    owners = {flag["code"]: flag["initial_owner"] for flag in FLAGS}
    result = []
    for event in unique_capture_events(match["captures"]):
        if event["flag"] not in owners:
            continue
        owners[event["flag"]] = event["team"]
        values = set(owners.values())
        if len(values) == 1 and next(iter(values)) in (1, 2):
            result.append(event)
    return result


def samples_before_events(matches, event_selector, seconds=EVENT_WINDOW_SECONDS):
    selected = []
    for match in matches:
        for event in event_selector(match):
            start = event["time"] - timedelta(seconds=seconds)
            selected.extend(sample for sample in match["positions"] if start <= sample["time"] <= event["time"])
    return selected


def frags_before_events(matches, event_selector, seconds=EVENT_WINDOW_SECONDS):
    selected = []
    for match in matches:
        for event in event_selector(match):
            start = event["time"] - timedelta(seconds=seconds)
            selected.extend(frag for frag in match["frags"] if start <= frag["time"] <= event["time"])
    return selected


def load_fixture(path: Path):
    tables = parse_sql(path)
    match_rows = [row for row in tables["ktp_matches"] if row.get("map_name") == MAP_NAME and row.get("match_id")]
    if not match_rows:
        raise ValueError(f"No Anzio match in {path}")
    match_row = match_rows[-1]
    match_id = match_row["match_id"]
    teams = {
        integer(row["player_id"]): integer(row["team"])
        for row in tables["ktp_match_players"]
        if row.get("match_id") == match_id
    }
    positions = []
    for row in tables["ktp_position_samples"]:
        if row.get("match_id") != match_id or row.get("pos_x") is None or row.get("pos_y") is None:
            continue
        positions.append({
            "player": integer(row["player_id"]), "team": integer(row["team"]),
            "half": integer(row["half"]), "x": number(row["pos_x"]), "y": number(row["pos_y"]),
            "game_time": number(row["game_time"]), "time": dt(row["event_time"]), "match": match_id,
        })
    positions_by_player = defaultdict(list)
    for sample in positions:
        positions_by_player[sample["player"]].append(sample)
    for samples in positions_by_player.values():
        samples.sort(key=lambda item: item["time"])

    frags, raw_frag_count = [], 0
    for row in tables["hlstats_Events_Frags"]:
        if row.get("match_id") != match_id or row.get("map") != MAP_NAME:
            continue
        raw_frag_count += 1
        if any(row.get(key) is None for key in ("pos_x", "pos_y", "pos_victim_x", "pos_victim_y")):
            continue
        killer_x, killer_y = number(row["pos_x"]), number(row["pos_y"])
        victim_x, victim_y = number(row["pos_victim_x"]), number(row["pos_victim_y"])
        frags.append({
            "killer": integer(row["killerId"]), "victim": integer(row["victimId"]),
            "killer_team": teams.get(integer(row["killerId"]), 0),
            "victim_team": teams.get(integer(row["victimId"]), 0),
            "weapon": row.get("weapon") or "unknown", "weapon_group": weapon_group(row.get("weapon") or ""),
            "headshot": integer(row.get("headshot")) == 1,
            "role": row.get("killerRole") or "Unknown", "half": integer(row.get("half"), 1),
            "killer_x": killer_x, "killer_y": killer_y, "victim_x": victim_x, "victim_y": victim_y,
            "distance": distance(killer_x, killer_y, victim_x, victim_y),
            "time": dt(row["eventTime"]), "match": match_id,
        })

    damage = []
    for row in tables["ktp_damage_events"]:
        if row.get("match_id") != match_id:
            continue
        damage.append({
            "attacker": integer(row["attacker_id"]), "victim": integer(row["victim_id"]),
            "team": teams.get(integer(row["attacker_id"]), 0), "amount": number(row.get("damage_capped")),
            "time": dt(row["event_time"]), "half": integer(row.get("half"), 1), "match": match_id,
        })

    captures = []
    for row in tables["ktp_flag_captures"]:
        if row.get("match_id") != match_id:
            continue
        team_text = (row.get("team") or "").lower()
        team = 1 if team_text in {"allies", "1"} else 2 if team_text in {"axis", "2"} else 0
        captures.append({"flag": row.get("flag_name"), "team": team, "half": integer(row.get("half"), 1), "time": dt(row["event_time"]), "match": match_id})

    action_codes = {integer(row["id"]): row.get("code") for row in tables["hlstats_Actions"]}
    cap_breaks = []
    for row in tables["hlstats_Events_PlayerActions"]:
        if row.get("match_id") == match_id and action_codes.get(integer(row.get("actionId"))) == "cap_break":
            cap_breaks.append({"time": dt(row["eventTime"]), "half": 1, "match": match_id})

    return {
        "id": match_id, "source": str(path), "start": dt(match_row["start_time"]), "end": dt(match_row.get("end_time")),
        "teams": teams, "positions": positions, "positions_by_player": positions_by_player,
        "frags": sorted(frags, key=lambda item: item["time"]), "raw_frag_count": raw_frag_count,
        "damage": damage, "captures": captures, "cap_breaks": cap_breaks,
    }


def make_heatmap(name, title, detail, values, palette="orange", category="Core", signed=False):
    return {
        "name": name, "type": "signed" if signed else "heatmap", "title": title, "detail": detail,
        "palette": palette, "category": category, "cells": cells_payload(values),
    }


def make_balance(name, title, detail, kills, deaths, category="Core"):
    keys = sorted(set(kills) | set(deaths))
    return {
        "name": name, "type": "balance", "title": title, "detail": detail, "category": category,
        "cells": [{"key": key, "kills": float(kills.get(key, 0)), "deaths": float(deaths.get(key, 0))} for key in keys],
    }


def make_placeholder(name, title, detail, message, category):
    return {"name": name, "type": "placeholder", "title": title, "detail": detail, "message": message, "category": category}


def objective_rows(match, damage_points):
    rows = []
    for flag in FLAGS:
        near_samples = [s for s in match["positions"] if distance(s["x"], s["y"], flag["x"], flag["y"]) <= OBJECTIVE_RADIUS]
        near_kills = [f for f in match["frags"] if distance(f["killer_x"], f["killer_y"], flag["x"], flag["y"]) <= OBJECTIVE_RADIUS]
        near_deaths = [f for f in match["frags"] if distance(f["victim_x"], f["victim_y"], flag["x"], flag["y"]) <= OBJECTIVE_RADIUS]
        near_damage = [d for d in damage_points if distance(d["x"], d["y"], flag["x"], flag["y"]) <= OBJECTIVE_RADIUS]
        minutes = len(near_samples) * SAMPLE_SECONDS / 60.0
        kills, deaths = len(near_kills), len(near_deaths)
        rows.append({
            "Flag": flag["name"], "Occ min": f"{minutes:.1f}", "Kills": str(kills), "Deaths": str(deaths),
            "K/min": f"{kills / minutes:.2f}" if minutes else "n/a",
            "D/min": f"{deaths / minutes:.2f}" if minutes else "n/a",
            "Dmg/min*": f"{sum(d['amount'] for d in near_damage) / minutes:.1f}" if minutes else "n/a",
            "Min/death": f"{minutes / deaths:.2f}" if deaths else "n/a",
        })
    return rows


def build_atlas(matches, target_id):
    target = next((match for match in matches if match["id"] == target_id), None)
    if target is None:
        raise ValueError(f"Target match {target_id!r} was not found")
    baseline_matches = [match for match in matches if match is not target]
    all_positions = [sample for match in matches for sample in match["positions"]]
    all_frags = [frag for match in matches for frag in match["frags"]]
    target_positions, target_frags = target["positions"], target["frags"]

    target_occ = aggregate_cells(target_positions, point="sample", weight=SAMPLE_SECONDS)
    target_occ_allies = aggregate_cells([s for s in target_positions if s["team"] == 1], point="sample", weight=SAMPLE_SECONDS)
    target_occ_axis = aggregate_cells([s for s in target_positions if s["team"] == 2], point="sample", weight=SAMPLE_SECONDS)
    target_kills = aggregate_cells(target_frags, "killer")
    target_deaths = aggregate_cells(target_frags, "victim")
    target_kill_rate = rate_cells(target_kills, target_occ, TARGET_CELL_MINIMUM_SECONDS)
    target_death_rate = rate_cells(target_deaths, target_occ, TARGET_CELL_MINIMUM_SECONDS)
    target_net_rate = {key: target_kill_rate.get(key, 0) - target_death_rate.get(key, 0) for key in set(target_kill_rate) | set(target_death_rate)}

    panels = []
    panels.append(make_heatmap("01-target-aggregate-occupancy.png", "Aggregate occupancy", f"Target bot match | {SAMPLE_SECONDS:g}-second samples | all players combined", target_occ, "cyan"))
    panels.append(make_heatmap("02-target-kill-origins.png", "Kill origins", "Target bot match | aggregate killer positions", target_kills, "gold"))
    panels.append(make_heatmap("03-target-death-locations.png", "Death locations", "Target bot match | aggregate victim positions", target_deaths, "red"))
    panels.append(make_balance("04-target-kill-death-balance.png", "Kill/death balance", "Gold = more kills | red = more deaths | brightness = volume", target_kills, target_deaths))
    panels.append(make_heatmap("05-target-kills-per-occupancy-minute.png", "Kills per occupancy minute", f"Target | cells require >={TARGET_CELL_MINIMUM_SECONDS:g} seconds occupancy", target_kill_rate, "gold"))
    panels.append(make_heatmap("06-target-deaths-per-occupancy-minute.png", "Deaths per occupancy minute", f"Target | cells require >={TARGET_CELL_MINIMUM_SECONDS:g} seconds occupancy", target_death_rate, "red"))
    panels.append(make_heatmap("07-target-net-frags-per-occupancy-minute.png", "Net frags per occupancy minute", f"Target | positive gold, negative red | cells require >={TARGET_CELL_MINIMUM_SECONDS:g} seconds occupancy", target_net_rate, "gold", signed=True))

    for index, (team, label, palette) in enumerate(((1, "Allies", "blue"), (2, "Axis", "red")), start=8):
        team_frags = [f for f in target_frags if f["killer_team"] == team]
        panels.append(make_balance(f"{index:02d}-target-{label.lower()}-kill-death.png", f"{label} kill/death locations", "Target | aggregate team split", aggregate_cells(team_frags, "killer"), aggregate_cells(team_frags, "victim"), "Team and side"))

    control = {}
    for key in set(target_occ_allies) | set(target_occ_axis):
        allies, axis = target_occ_allies.get(key, 0), target_occ_axis.get(key, 0)
        if allies + axis >= 15:
            control[key] = (allies - axis) / (allies + axis)
    panels.append(make_heatmap("10-target-team-control-differential.png", "Team control differential", "Blue = Allies occupancy | red = Axis occupancy | normalized within each cell", control, "blue", "Team and side", signed=True))

    halves = sorted({frag["half"] for frag in target_frags})
    for half in halves:
        half_frags = [frag for frag in target_frags if frag["half"] == half]
        panels.append(make_balance(f"11-target-half-{half}-kill-death.png", f"Half {half} kill/death locations", "Target | aggregate half split", aggregate_cells(half_frags, "killer"), aggregate_cells(half_frags, "victim"), "Dimensions"))
    if 2 not in halves:
        panels.append(make_placeholder("12-target-half-2-coverage.png", "Half 2 coverage", "Target bot corpus", "No second-half data exists in these fixtures. This panel makes the coverage gap explicit.", "Dimensions"))

    roles = sorted({frag["role"] for frag in target_frags})
    for role in roles:
        role_frags = [frag for frag in target_frags if frag["role"] == role]
        safe = re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-") or "unknown"
        panels.append(make_balance(f"13-target-role-{safe}-kill-death.png", f"Role: {role}", "Target | aggregate role split", aggregate_cells(role_frags, "killer"), aggregate_cells(role_frags, "victim"), "Dimensions"))

    headshots = [frag for frag in target_frags if frag["headshot"]]
    panels.append(make_balance("14-target-headshot-kill-death.png", "Headshot combat locations", "Target | coordinate-bearing headshot frags", aggregate_cells(headshots, "killer"), aggregate_cells(headshots, "victim"), "Dimensions"))
    distance_bands = [
        ("close", "Close (<256 units)", lambda d: d < 256),
        ("medium", "Medium (256-768 units)", lambda d: 256 <= d <= 768),
        ("long", "Long (>768 units)", lambda d: d > 768),
    ]
    for number_, (slug, label, predicate) in enumerate(distance_bands, start=15):
        band = [frag for frag in target_frags if predicate(frag["distance"])]
        panels.append(make_balance(f"{number_:02d}-target-distance-{slug}.png", label, f"Target | {len(band)} coordinate-bearing frags", aggregate_cells(band, "killer"), aggregate_cells(band, "victim"), "Dimensions"))

    groups = sorted({frag["weapon_group"] for frag in target_frags})
    for offset, group in enumerate(groups, start=18):
        group_frags = [frag for frag in target_frags if frag["weapon_group"] == group]
        panels.append(make_balance(f"{offset:02d}-target-weapon-{group}.png", f"Weapon class: {group}", f"Target | {len(group_frags)} coordinate-bearing frags", aggregate_cells(group_frags, "killer"), aggregate_cells(group_frags, "victim"), "Dimensions"))

    target_vectors = [{"x1": f["killer_x"], "y1": f["killer_y"], "x2": f["victim_x"], "y2": f["victim_y"], "count": 1, "headshot_rate": 1 if f["headshot"] else 0} for f in target_frags]
    panels.append({"name": "25-target-kill-angles.png", "type": "vectors", "title": "Kill angles", "detail": "Target | one aggregate line per coordinate-bearing frag | no player routes", "category": "Combat patterns", "vectors": target_vectors})

    lane_groups = defaultdict(list)
    for frag in all_frags:
        lane_groups[(cell_key(frag["killer_x"], frag["killer_y"]), cell_key(frag["victim_x"], frag["victim_y"]))].append(frag)
    lanes = []
    for (origin, destination), frags in lane_groups.items():
        if len(frags) < RECURRING_LANE_MINIMUM:
            continue
        x1, y1 = cell_center(origin); x2, y2 = cell_center(destination)
        lanes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "count": len(frags), "headshot_rate": sum(f["headshot"] for f in frags) / len(frags)})
    panels.append({"name": "26-corpus-recurring-kill-lanes.png", "type": "vectors", "title": "Recurring kill lanes", "detail": f"Five-match bot corpus | origin-to-victim cell pairs repeated >={RECURRING_LANE_MINIMUM} times", "category": "Combat patterns", "vectors": sorted(lanes, key=lambda item: item["count"])})

    opening_duels, opening_window = [], []
    for match in matches:
        for half in sorted({frag["half"] for frag in match["frags"]}):
            half_frags = [frag for frag in match["frags"] if frag["half"] == half]
            if not half_frags:
                continue
            half_start = match["start"] if half == 1 else min(frag["time"] for frag in half_frags)
            window = [frag for frag in half_frags if 0 <= (frag["time"] - half_start).total_seconds() <= OPENING_SECONDS]
            opening_window.extend(window)
            if window:
                opening_duels.append(window[0])
    panels.append(make_balance("27-corpus-opening-duels.png", "Opening duels", "Five-match bot corpus | first frag within 45 seconds of each observed half start", aggregate_cells(opening_duels, "killer"), aggregate_cells(opening_duels, "victim"), "Combat patterns"))
    panels.append(make_balance("28-corpus-opening-window-combat.png", "Opening-window combat", "Five-match bot corpus | all frags in first 45 seconds of observed half starts", aggregate_cells(opening_window, "killer"), aggregate_cells(opening_window, "victim"), "Combat patterns"))

    trades, multikills = [], []
    for match in matches:
        frags = match["frags"]
        for index, frag in enumerate(frags):
            for prior in reversed(frags[:index]):
                gap = (frag["time"] - prior["time"]).total_seconds()
                if gap > TRADE_SECONDS:
                    break
                if frag["victim"] == prior["killer"] and frag["killer_team"] == prior["victim_team"] and frag["killer_team"]:
                    trades.append(frag)
                    break
            prior_same = next((prior for prior in reversed(frags[:index]) if prior["killer"] == frag["killer"]), None)
            if prior_same and (frag["time"] - prior_same["time"]).total_seconds() <= MULTIKILL_SECONDS:
                multikills.extend([prior_same, frag])
    multikills = list({(f["match"], f["time"], f["killer"], f["victim"]): f for f in multikills}.values())
    panels.append(make_balance("29-corpus-trade-kills.png", "Trade kills", f"Five-match bot corpus | retaliation on prior killer within {TRADE_SECONDS:.0f} seconds", aggregate_cells(trades, "killer"), aggregate_cells(trades, "victim"), "Combat patterns"))
    panels.append(make_balance("30-corpus-fast-multikills.png", "Fast multikills", f"Five-match bot corpus | same killer, consecutive personal kills <= {MULTIKILL_SECONDS:.0f} seconds", aggregate_cells(multikills, "killer"), aggregate_cells(multikills, "victim"), "Combat patterns"))

    isolated, isolation_evaluable = [], 0
    for match in matches:
        for frag in match["frags"]:
            teammates = [pid for pid, team in match["teams"].items() if team == frag["victim_team"] and pid != frag["victim"]]
            nearby = False; evaluable = False
            for teammate in teammates:
                sample = nearest_position(match, teammate, frag["time"])
                if sample is None:
                    continue
                evaluable = True
                if distance(sample["x"], sample["y"], frag["victim_x"], frag["victim_y"]) <= ISOLATION_RADIUS:
                    nearby = True
                    break
            if evaluable:
                isolation_evaluable += 1
                if not nearby:
                    isolated.append(frag)
    panels.append(make_heatmap("31-corpus-isolated-deaths.png", "Isolated deaths", f"Five-match bot corpus | no sampled teammate within {ISOLATION_RADIUS:.0f} units | {len(isolated)}/{isolation_evaluable} evaluable deaths", aggregate_cells(isolated, "victim"), "red", "Combat patterns"))

    capture_selector = lambda match: unique_capture_events(match["captures"])
    before_captures = samples_before_events(matches, capture_selector)
    combat_before_captures = frags_before_events(matches, capture_selector)
    panels.append(make_heatmap("32-corpus-pre-capture-occupancy.png", "Occupancy before captures", f"Five-match bot corpus | aggregate samples in {EVENT_WINDOW_SECONDS:g} seconds before each unique capture event", aggregate_cells(before_captures, "sample", SAMPLE_SECONDS), "purple", "Objective windows"))
    panels.append(make_balance("33-corpus-pre-capture-combat.png", "Combat before captures", f"Five-match bot corpus | aggregate frags in {EVENT_WINDOW_SECONDS:g} seconds before each unique capture event", aggregate_cells(combat_before_captures, "killer"), aggregate_cells(combat_before_captures, "victim"), "Objective windows"))
    before_breaks = samples_before_events(matches, lambda match: match["cap_breaks"])
    if before_breaks:
        panels.append(make_heatmap("34-corpus-pre-cap-break-occupancy.png", "Occupancy before cap breaks", f"Five-match bot corpus | aggregate samples in {EVENT_WINDOW_SECONDS:g} seconds before cap_break actions", aggregate_cells(before_breaks, "sample", SAMPLE_SECONDS), "purple", "Objective windows"))
    else:
        panels.append(make_placeholder("34-corpus-pre-cap-break-coverage.png", "Cap-break window coverage", "Five-match bot corpus", "No cap-break events were available to populate a pre-event window.", "Objective windows"))
    capouts = [(match, event) for match in matches for event in reconstruct_capouts(match)]
    before_capouts = samples_before_events(matches, reconstruct_capouts)
    if before_capouts:
        panels.append(make_heatmap("35-corpus-pre-capout-occupancy.png", "Occupancy before reconstructed capouts", f"Five-match bot corpus | {EVENT_WINDOW_SECONDS:g} seconds before all-five-flags-owned transitions", aggregate_cells(before_capouts, "sample", SAMPLE_SECONDS), "purple", "Objective windows"))
    else:
        panels.append(make_placeholder("35-corpus-pre-capout-coverage.png", "Capout window coverage", "Five-match bot corpus", "No all-five-flags-owned transition could be reconstructed from these capture timelines.", "Objective windows"))

    damage_points = []
    for match in matches:
        for event in match["damage"]:
            sample = nearest_position(match, event["attacker"], event["time"])
            if sample:
                damage_points.append({"x": sample["x"], "y": sample["y"], "amount": event["amount"], "match": match["id"]})
    target_damage_points = [event for event in damage_points if event["match"] == target["id"]]
    panels.append(make_heatmap("36-target-sample-aligned-damage.png", "Sample-aligned damage", f"Target | capped damage assigned to nearest attacker sample within {NEAREST_SAMPLE_SECONDS:.0f}s | {len(target_damage_points)}/{len(target['damage'])} events aligned", aggregate_cells(target_damage_points, "sample", lambda event: event["amount"]), "orange", "Objective efficiency"))

    objective_columns = ["Flag", "Occ min", "Kills", "Deaths", "K/min", "D/min", "Dmg/min*", "Min/death"]
    panels.append({"name": "37-target-objective-efficiency.png", "type": "table", "title": "Objective-area efficiency", "detail": f"Target | within {OBJECTIVE_RADIUS:.0f} units | *damage uses nearest <={NEAREST_SAMPLE_SECONDS:g}s sample", "category": "Objective efficiency", "columns": objective_columns, "rows": objective_rows(target, target_damage_points)})

    side_rows = []
    for flag in FLAGS:
        row = {"Flag": flag["name"]}
        for team, label in ((1, "Allies"), (2, "Axis")):
            samples = [s for s in target_positions if s["team"] == team and distance(s["x"], s["y"], flag["x"], flag["y"]) <= OBJECTIVE_RADIUS]
            kills = [f for f in target_frags if f["killer_team"] == team and distance(f["killer_x"], f["killer_y"], flag["x"], flag["y"]) <= OBJECTIVE_RADIUS]
            deaths = [f for f in target_frags if f["victim_team"] == team and distance(f["victim_x"], f["victim_y"], flag["x"], flag["y"]) <= OBJECTIVE_RADIUS]
            row[f"{label} min"] = f"{len(samples) * SAMPLE_SECONDS / 60:.1f}"
            row[f"{label} K/D"] = f"{len(kills)}/{len(deaths)}"
        side_rows.append(row)
    panels.append({"name": "38-target-side-imbalance.png", "type": "table", "title": "Allies vs Axis objective control", "detail": f"Target | aggregate within {OBJECTIVE_RADIUS:.0f} units of each flag", "category": "Team and side", "columns": ["Flag", "Allies min", "Allies K/D", "Axis min", "Axis K/D"], "rows": side_rows})

    corpus_occ = aggregate_cells(all_positions, "sample", SAMPLE_SECONDS)
    corpus_kills = aggregate_cells(all_frags, "killer")
    corpus_deaths = aggregate_cells(all_frags, "victim")
    corpus_kill_rate = rate_cells(corpus_kills, corpus_occ, CORPUS_CELL_MINIMUM_SECONDS)
    corpus_death_rate = rate_cells(corpus_deaths, corpus_occ, CORPUS_CELL_MINIMUM_SECONDS)
    panels.append(make_heatmap("39-corpus-average-occupancy.png", "Average occupancy per match", "Five-match bot corpus | seconds per cell divided by five", corpus_occ, "cyan", "Baselines"))
    panels[-1]["cells"] = cells_payload(corpus_occ, 1.0 / len(matches))
    panels.append(make_heatmap("40-corpus-kills-per-occupancy-minute.png", "Corpus kills per occupancy minute", f"Five-match bot corpus | cells require >={CORPUS_CELL_MINIMUM_SECONDS:g} aggregate occupancy seconds", corpus_kill_rate, "gold", "Baselines"))
    panels.append(make_heatmap("41-corpus-deaths-per-occupancy-minute.png", "Corpus deaths per occupancy minute", f"Five-match bot corpus | cells require >={CORPUS_CELL_MINIMUM_SECONDS:g} aggregate occupancy seconds", corpus_death_rate, "red", "Baselines"))

    baseline_positions = [s for match in baseline_matches for s in match["positions"]]
    baseline_frags = [f for match in baseline_matches for f in match["frags"]]
    base_occ = aggregate_cells(baseline_positions, "sample", SAMPLE_SECONDS)
    base_kill_rate = rate_cells(aggregate_cells(baseline_frags, "killer"), base_occ, CORPUS_CELL_MINIMUM_SECONDS)
    base_death_rate = rate_cells(aggregate_cells(baseline_frags, "victim"), base_occ, CORPUS_CELL_MINIMUM_SECONDS)
    panels.append(make_heatmap("42-target-vs-baseline-kill-rate.png", "Kill-rate delta vs baseline", "Target minus other four bot matches | gold positive, red negative", signed_delta(target_kill_rate, base_kill_rate, set(target_kill_rate), set(base_kill_rate)), "gold", "Baselines", signed=True))
    panels.append(make_heatmap("43-target-vs-baseline-death-rate.png", "Death-rate delta vs baseline", "Target minus other four bot matches | gold positive, red negative", signed_delta(target_death_rate, base_death_rate, set(target_death_rate), set(base_death_rate)), "gold", "Baselines", signed=True))
    target_total, base_total = sum(target_occ.values()), sum(base_occ.values())
    target_share = {key: value / target_total * 100 for key, value in target_occ.items()}
    base_share = {key: value / base_total * 100 for key, value in base_occ.items()}
    panels.append(make_heatmap("44-target-vs-baseline-occupancy-share.png", "Occupancy-share delta vs baseline", "Target minus other four bot matches | percentage-point share by cell", signed_delta(target_share, base_share), "gold", "Baselines", signed=True))

    def match_summary(match):
        duration = (match["end"] - match["start"]).total_seconds() / 60 if match["end"] else 0
        return {"Match": "Target" if match is target else "Baseline", "Minutes": f"{duration:.1f}", "Samples": str(len(match["positions"])), "Frags": str(len(match["frags"])), "Captures": str(len(unique_capture_events(match["captures"]))), "Cap breaks": str(len(match["cap_breaks"])), "Damage": str(len(match["damage"]))}
    summary_rows = [match_summary(target)]
    baseline_totals = {"Match": "Other 4 avg"}
    for key in ("Minutes", "Samples", "Frags", "Captures", "Cap breaks", "Damage"):
        baseline_totals[key] = f"{sum(float(match_summary(m)[key]) for m in baseline_matches) / len(baseline_matches):.1f}"
    summary_rows.append(baseline_totals)
    panels.append({"name": "45-target-vs-baseline-summary.png", "type": "table", "title": "Target vs leave-one-match-out baseline", "detail": "Current comparison corpus is synthetic bot data, not a competitive-match benchmark", "category": "Baselines", "columns": ["Match", "Minutes", "Samples", "Frags", "Captures", "Cap breaks", "Damage"], "rows": summary_rows})

    coverage_rows = [
        {"Dimension": "Matches", "Available": str(len(matches)), "Notes": f"All {MAP_NAME} bot fixtures"},
        {"Dimension": "Position samples", "Available": str(len(all_positions)), "Notes": f"{SAMPLE_SECONDS:g}-second periodic samples"},
        {"Dimension": "Coordinate frags", "Available": f"{len(all_frags)}/{sum(m['raw_frag_count'] for m in matches)}", "Notes": "Rows without both endpoints excluded"},
        {"Dimension": "Halves", "Available": ", ".join(map(str, sorted({f['half'] for f in all_frags}))), "Notes": "No inferred second-half data"},
        {"Dimension": "Roles", "Available": ", ".join(sorted({f['role'] for f in all_frags})), "Notes": "Bot role coverage"},
        {"Dimension": "Weapon classes", "Available": ", ".join(sorted({f['weapon_group'] for f in all_frags})), "Notes": "Semantic groups"},
        {"Dimension": "Trade kills", "Available": str(len(trades)), "Notes": f"Retaliation <= {TRADE_SECONDS:.0f}s"},
        {"Dimension": "Fast multikill frags", "Available": str(len(multikills)), "Notes": f"Same killer <= {MULTIKILL_SECONDS:.0f}s"},
        {"Dimension": "Reconstructed capouts", "Available": str(len(capouts)), "Notes": "From capture ownership transitions"},
        {"Dimension": "Damage aligned", "Available": f"{len(damage_points)}/{sum(len(m['damage']) for m in matches)}", "Notes": f"Nearest attacker sample <={NEAREST_SAMPLE_SECONDS:g}s"},
        {"Dimension": "Grenade explosions", "Available": "Deferred", "Notes": "Requires explicit explosion persistence"},
    ]
    panels.append({"name": "46-atlas-coverage-and-limitations.png", "type": "table", "title": "Atlas coverage and limitations", "detail": "Every public layer is aggregate-only; no player heatmaps or routes", "category": "Coverage", "columns": ["Dimension", "Available", "Notes"], "rows": coverage_rows})

    cover_rows = [
        {"Section": "Core", "Images": "7", "Purpose": "Occupancy, kills, deaths, normalized efficiency"},
        {"Section": "Team/dimensions", "Images": str(sum(p["category"] in {"Team and side", "Dimensions"} for p in panels)), "Purpose": "Side, half, role, headshot, range, weapon"},
        {"Section": "Combat patterns", "Images": str(sum(p["category"] == "Combat patterns" for p in panels)), "Purpose": "Angles, lanes, openings, trades, multikills, isolation"},
        {"Section": "Objective windows", "Images": str(sum(p["category"] == "Objective windows" for p in panels)), "Purpose": f"{EVENT_WINDOW_SECONDS:g} seconds before captures, breaks, capouts"},
        {"Section": "Objective efficiency", "Images": str(sum(p["category"] == "Objective efficiency" for p in panels)), "Purpose": "Damage and flag-area efficiency"},
        {"Section": "Baselines", "Images": str(sum(p["category"] == "Baselines" for p in panels)), "Purpose": "Five-match corpus and target comparison"},
    ]
    cover = {"name": "00-spatial-atlas-overview.png", "type": "table", "title": "Anzio spatial analytics atlas", "detail": f"{len(matches)} local bot matches | target plus leave-one-out baseline | aggregate-only", "category": "Overview", "columns": ["Section", "Images", "Purpose"], "rows": cover_rows}
    panels.insert(0, cover)

    return {
        "schema_version": 1,
        "map": MAP_NAME,
        "map_config_schema_version": int(MAP_CONFIG["schema_version"]),
        "grid_size": GRID,
        "flags": [{key: flag[key] for key in ("name", "x", "y")} for flag in FLAGS],
        "privacy": "Aggregate-only. No player names, identifiers, Steam IDs, individual heatmaps, or player routes.",
        "summary": {
            "matches": len(matches), "target_coordinate_frags": len(target_frags), "target_raw_frags": target["raw_frag_count"],
            "corpus_coordinate_frags": len(all_frags), "corpus_raw_frags": sum(m["raw_frag_count"] for m in matches),
            "position_samples": len(all_positions), "capture_events": sum(len(unique_capture_events(m["captures"])) for m in matches),
            "cap_breaks": sum(len(m["cap_breaks"]) for m in matches), "reconstructed_capouts": len(capouts),
            "trade_kills": len(trades), "fast_multikill_frags": len(multikills), "isolated_deaths": len(isolated),
            "damage_aligned": len(damage_points), "damage_total": sum(len(m["damage"]) for m in matches),
        },
        "panels": panels,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", action="append", type=Path, required=True)
    parser.add_argument("--target-match", required=True)
    parser.add_argument("--map-config", type=Path, default=DEFAULT_MAP_CONFIG)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    configure_map(args.map_config.resolve())
    matches = [load_fixture(path.resolve()) for path in args.fixture]
    atlas = build_atlas(matches, args.target_match)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(atlas, indent=2), encoding="utf-8")
    print(json.dumps(atlas["summary"], indent=2))


if __name__ == "__main__":
    main()
