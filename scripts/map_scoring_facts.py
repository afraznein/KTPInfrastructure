#!/usr/bin/env python3
"""Per-map DoD clan-scoring facts, parsed from the server configs.

The configs in KTPDoDServerConfig are the ONLY place the tick model lives, and
Nein edits them per map. Rather than keep a hand-written copy that drifts, this
reads the config tree and emits the facts; `--check` fails when a committed
copy no longer matches, so drift is a red check and not a silent wrong number.

What each map contributes (see `ktpbasic.cfg` for the defaults it overrides):

  mp_clan_scoring_values_allies/_axis   one digit per flag, the per-tick point
                                        value that flag is worth to that side.
                                        ⚠️ The string is REVERSED against HUD
                                        order — the config says so itself. This
                                        script stores HUD order (flag 1 first).
  mp_clan_scoring_delay                 seconds per tick (30 default; 15 on
                                        cal_sherman2).
  mp_clan_scoring_bonus_allies/_axis    the capout bonus, awarded for holding
                                        every flag (40 default; 60 on a few).

These drive the TEAM score line. They are NOT the player ObjScore: that is
`SUM(captures x CP_points_for_cap)`, a per-flag map-entity value captured in
`ktp_flag_positions.points_for_cap` (migration 032). Two different quantities;
see handover/SCOREBOARD_ALIGNMENT_MODEL_20260922.md.

TWO WAYS A READER OF THE EMITTED JSON GETS A FALSE ANSWER, both hit on 2026-10-01
while chasing a saints mismatch that did not exist.

  A `map_config` entry that no map points at is a CONFIG FILE that exists, not
  dead data: entries come from the config tree, one per cfg. Pruning one deletes
  a fact, and its presence is not evidence any map still uses it.

  Both analytics files nest their maps under a `maps` key — a list here, an object
  in map_flag_facts.json — so a top-level key scan returns nothing and reads as
  "the map is not configured". Read one row's shape before trusting a lookup, and
  read the file from `git show origin/main:<path>`: the data server's checkout is
  deliberately stale and answers zero to questions main answers.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# ktpbasic.cfg's values, applied where a map config does not override them.
BASE_DEFAULTS = {"scoring_delay_seconds": 30, "capout_bonus_allies": 40, "capout_bonus_axis": 40}

CVARS = {
    "values_allies": "mp_clan_scoring_values_allies",
    "values_axis": "mp_clan_scoring_values_axis",
    "scoring_delay_seconds": "mp_clan_scoring_delay",
    "capout_bonus_allies": "mp_clan_scoring_bonus_allies",
    "capout_bonus_axis": "mp_clan_scoring_bonus_axis",
}


def read_cvar(text: str, cvar: str) -> str | None:
    """Last uncommented assignment wins — the configs keep old values as `//` lines."""
    found = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        match = re.match(rf"{re.escape(cvar)}\s+(\S+)", stripped)
        if match:
            found = match.group(1)
    return found


def parse_config(path: Path, defaults: dict) -> dict | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    allies = read_cvar(text, CVARS["values_allies"])
    axis = read_cvar(text, CVARS["values_axis"])
    if not allies or not axis:
        return None
    if not allies.isdigit() or not axis.isdigit() or len(allies) != len(axis):
        raise SystemExit(f"{path.name}: scoring value strings are malformed ({allies!r}/{axis!r})")

    def number(key: str) -> int:
        raw = read_cvar(text, CVARS[key])
        return int(raw) if raw is not None and raw.lstrip("-").isdigit() else defaults[key]

    # Stored in HUD order. The config writes them reversed.
    return {
        "map_config": path.stem.removeprefix("ktp_"),
        "flags": len(allies),
        "tick_value_allies": [int(c) for c in reversed(allies)],
        "tick_value_axis": [int(c) for c in reversed(axis)],
        "scoring_delay_seconds": number("scoring_delay_seconds"),
        "capout_bonus_allies": number("capout_bonus_allies"),
        "capout_bonus_axis": number("capout_bonus_axis"),
    }


def build(config_root: Path) -> dict:
    basic = config_root / "ktpbasic.cfg"
    defaults = dict(BASE_DEFAULTS)
    if basic.is_file():
        text = basic.read_text(encoding="utf-8", errors="replace")
        for key in ("scoring_delay_seconds", "capout_bonus_allies", "capout_bonus_axis"):
            raw = read_cvar(text, CVARS[key])
            if raw is not None and raw.isdigit():
                defaults[key] = int(raw)

    maps = []
    for path in sorted(config_root.glob("ktp_*.cfg")):
        entry = parse_config(path, defaults)
        if entry is not None:
            maps.append(entry)
    if not maps:
        raise SystemExit(f"no map configs with scoring values under {config_root}")

    return {
        "source": "KTPDoDServerConfig/serverfiles/dod/configs",
        "source_revision": git_revision(config_root),
        "defaults": defaults,
        "note": "tick values are HUD order; the configs store them reversed",
        "maps": maps,
    }


def git_revision(path: Path) -> str | None:
    """Provenance, so a stale copy names the commit it was cut from."""
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def merge_flag_facts(facts: dict, flag_path: Path) -> dict:
    """Attach the curated per-flag block (spawn ownership, capture value).

    The configs do not carry either. `initial_owner` is the one the review
    asked for: a flag that spawns neutral (0) is new ground on its first
    capture, while 1/2 is a flip of known ground — the distinction any
    pressure or first-blood metric needs, and it cannot be read off a
    capture count.
    """
    curated = json.loads(flag_path.read_text(encoding="utf-8"))
    by_config: dict[str, dict] = {m["map_config"]: m for m in facts["maps"]}
    merged = []
    for map_name, entry in sorted(curated["maps"].items()):
        scoring = by_config.get(entry.get("config") or "", None)
        merged.append({
            "map_name": map_name,
            "map_config": entry.get("config"),
            "flags": entry["flags"],
            "flag_facts_source": entry.get("source"),
            # Null when no config is mapped: the team-line tick model is then
            # unavailable for that map, which is a stated gap, not a zero.
            "tick_value_allies": scoring["tick_value_allies"] if scoring else None,
            "tick_value_axis": scoring["tick_value_axis"] if scoring else None,
            "scoring_delay_seconds": scoring["scoring_delay_seconds"] if scoring else None,
            "capout_bonus_allies": scoring["capout_bonus_allies"] if scoring else None,
            "capout_bonus_axis": scoring["capout_bonus_axis"] if scoring else None,
        })
    facts = dict(facts)
    facts["maps_by_name"] = merged
    return facts


def verify_flags(flag_path: Path, export: Path) -> int:
    """Check the curated block against what production actually observed.

    Export is the TSV of:
      SELECT map_name, flag_index, flag_name, default_owner, points_for_cap
      FROM ktp_flag_positions WHERE default_owner IS NOT NULL
      GROUP BY map_name, flag_index, flag_name, default_owner, points_for_cap;

    A difference means the map file changed under us (or a new map arrived).
    That is a review trigger — this never rewrites the curated file.
    """
    curated = json.loads(flag_path.read_text(encoding="utf-8"))["maps"]
    rows = [line.rstrip("\n").split("\t")
            for line in export.read_text(encoding="utf-8").splitlines() if line.strip()]
    header, body = rows[0], rows[1:]
    observed: dict[str, dict[int, tuple[str, int, int]]] = {}
    for row in body:
        r = dict(zip(header, row))
        observed.setdefault(r["map_name"], {})[int(r["flag_index"])] = (
            r["flag_name"], int(r["default_owner"]), int(r["points_for_cap"]))

    problems = []
    for map_name, seen in sorted(observed.items()):
        entry = curated.get(map_name)
        if entry is None:
            problems.append(f"{map_name}: observed in production, absent from the curated file")
            continue
        have = {f["flag_index"]: (f["flag_name"], f["initial_owner"], f["cap_points"])
                for f in entry["flags"]}
        for index in sorted(set(have) | set(seen)):
            if have.get(index) != seen.get(index):
                problems.append(f"{map_name} flag {index}: curated {have.get(index)} "
                                f"vs observed {seen.get(index)}")
    for map_name in sorted(set(curated) - set(observed)):
        print(f"note: {map_name} is curated but unobserved in this export", file=sys.stderr)

    for line in problems:
        print(line, file=sys.stderr)
    if problems:
        print(f"{len(problems)} difference(s) — review the map, then update "
              f"{flag_path} deliberately", file=sys.stderr)
        return 1
    print(f"{flag_path} matches production for {len(observed)} map(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--configs", type=Path,
                    help="KTPDoDServerConfig/serverfiles/dod/configs")
    ap.add_argument("--out", type=Path, help="write JSON here (default: stdout)")
    ap.add_argument("--check", type=Path,
                    help="compare against this file and exit 1 on any difference")
    ap.add_argument("--markdown", action="store_true", help="print a table instead of JSON")
    ap.add_argument("--flags", type=Path,
                    help="curated per-flag facts (config/analytics/map_flag_facts.json)")
    ap.add_argument("--verify-flags", type=Path, metavar="EXPORT",
                    help="check --flags against a ktp_flag_positions TSV export and exit 1 on drift")
    args = ap.parse_args(argv)

    if args.verify_flags:
        if not args.flags:
            ap.error("--verify-flags needs --flags")
        return verify_flags(args.flags, args.verify_flags)
    if not args.configs:
        ap.error("--configs is required unless --verify-flags is given")

    facts = build(args.configs)
    if args.flags:
        facts = merge_flag_facts(facts, args.flags)

    if args.markdown:
        print("| map | flags | allies per tick (HUD order) | axis per tick | tick s | capout A/X |")
        print("|---|---|---|---|---|---|")
        for m in facts["maps"]:
            print(f"| {m['map_config']} | {m['flags']} | "
                  f"{'.'.join(str(v) for v in m['tick_value_allies'])} | "
                  f"{'.'.join(str(v) for v in m['tick_value_axis'])} | "
                  f"{m['scoring_delay_seconds']} | "
                  f"{m['capout_bonus_allies']}/{m['capout_bonus_axis']} |")
        return 0

    rendered = json.dumps(facts, indent=2, sort_keys=True) + "\n"

    if args.check:
        # The revision moves whenever anything in that repo changes, so it is
        # provenance and not part of the comparison.
        want = json.loads(args.check.read_text(encoding="utf-8"))
        have = json.loads(rendered)
        want.pop("source_revision", None)
        have.pop("source_revision", None)
        if want != have:
            print(f"{args.check} is stale against {args.configs}", file=sys.stderr)
            for m_have in have["maps"]:
                m_want = next((x for x in want["maps"]
                               if x["map_config"] == m_have["map_config"]), None)
                if m_want != m_have:
                    print(f"  {m_have['map_config']}: {m_want} -> {m_have}", file=sys.stderr)
            for m_want in want["maps"]:
                if not any(x["map_config"] == m_want["map_config"] for x in have["maps"]):
                    print(f"  {m_want['map_config']}: removed", file=sys.stderr)
            return 1
        print(f"{args.check} matches {args.configs}")
        return 0

    if args.out:
        args.out.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.out} ({len(facts['maps'])} maps)")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
