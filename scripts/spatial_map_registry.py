#!/usr/bin/env python3
"""Inventory KTP match maps and enforce explicit spatial-readiness gates.

Maps come from `ktp_maps.ini`, the map->config binding table KTPMatchHandler
itself reads. Discovery used to regex the `say KTP <map> Match Config Executed`
line out of each `ktp_*.cfg`, which is chat text bound to nothing: `ktp_saints.cfg`
announces `dod_saints` while serving `dod_saints2_b3e`, and most of the custom
pool was invisible to every count this script produced.

`human_matches` is derived, never hand-entered: it is the number of distinct
match ids per map in `ktp_capture_manifests`, read with --database. The registry
JSON used to carry it as a typed field nobody updated, so every map read zero
while the fleet had played dozens. A JSON that still carries one is a
validation error. Point --database at the production schema: the synthetic
lanes write their own.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:  # direct script execution
    from team_score_telemetry import MysqlCli, MysqlCommandError
except ModuleNotFoundError:  # package import in tests/tooling
    from scripts.team_score_telemetry import MysqlCli, MysqlCommandError


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAPS_INI = "config/local/ktp_maps.ini"
# Cosmetic only. A config's `say` line is chat text; it is not what binds the
# config to a map, and on the custom pool it routinely names a different map.
ANNOUNCED_MAP = re.compile(
    r"^\s*say\s+KTP\s+(?:CLASSIC\s+)?(dod_[A-Za-z0-9_]+)\s+Match\s+Config\s+Executed\s*$",
    re.IGNORECASE | re.MULTILINE,
)
INI_SECTION = re.compile(r"^\[([^\]]+)\]$")
INI_CONFIG = re.compile(r"^config\s*=\s*(\S+)\s*$", re.IGNORECASE)
REVIEW_FIELDS = (
    "overview_transform_reviewed",
    "flag_geometry_reviewed",
    "objective_topology_reviewed",
    "bot_waypoints_verified",
)


DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def human_match_counts(cli: Any, since: str | None = None) -> dict[str, int]:
    """Map name -> distinct captured match ids, from the production manifests."""
    where = ""
    if since is not None:
        if not DATE.fullmatch(since):
            raise ValueError(f"--since must be YYYY-MM-DD, got {since!r}")
        where = f"WHERE event_time >= '{since}' "
    rows = cli.execute(
        "SELECT map_name, COUNT(DISTINCT match_id) FROM ktp_capture_manifests "
        f"{where}GROUP BY map_name;"
    )
    counts: dict[str, int] = {}
    for line in rows.splitlines():
        if not line.strip():
            continue
        map_name, count = line.split("\t")
        counts[normalise_map_name(map_name)] = int(count)
    return counts


def hand_entered_human_matches(config: dict[str, Any]) -> list[str]:
    where = ["defaults"] if "human_matches" in (config.get("defaults") or {}) else []
    where += sorted(name for name, entry in (config.get("maps") or {}).items()
                    if "human_matches" in (entry or {}))
    return where


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def normalise_map_name(name: str) -> str:
    name = name.strip()
    if name.lower().endswith(".bsp"):
        name = name[: -len(".bsp")]
    return name.lower()


def parse_maps_ini(path: Path) -> dict[str, str]:
    """Map name -> match-config filename, read the way KTPMatchHandler reads it.

    Mirrors `load_map_mappings()` in `KTPMatchHandler.sma`: `;`/`#` comments,
    `[map]` sections normalised with the .bsp strip and lowercase, and only the
    first `config =` inside a section (the plugin clears the section after it).
    """
    bindings: dict[str, str] = {}
    section = ""
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line[0] in ";#":
            continue
        header = INI_SECTION.match(line)
        if header:
            section = normalise_map_name(header.group(1))
            continue
        body = INI_CONFIG.match(line)
        if body and section:
            bindings[section] = body.group(1).strip()
            section = ""
    return bindings


class Discovery:
    """What the map inventory found, and what it could not account for."""

    def __init__(self) -> None:
        self.maps: dict[str, list[str]] = {}
        self.errors: list[str] = []
        self.unresolved_bindings: list[str] = []
        self.unreferenced_configs: list[str] = []
        self.announcement_mismatches: list[str] = []


def discover_configs(config_dir: Path, maps_ini: Path, root: Path = ROOT) -> Discovery:
    """Inventory maps from the map->config bindings the server actually uses.

    Discovery keys on `ktp_maps.ini`, not on a config's `say` line: the say line
    is chat text nothing reads, and on the custom pool it names a different map
    than the one the config is bound to, which made most of the pool invisible.
    """
    found = Discovery()
    if not maps_ini.is_file():
        found.errors.append(f"{display_path(maps_ini, root)}: map bindings file not found")
        return found

    bindings = parse_maps_ini(maps_ini)
    if not bindings:
        found.errors.append(f"{display_path(maps_ini, root)}: no [map] section declares a config")
        return found

    configs_for: dict[Path, list[str]] = {}
    for map_name, config_name in sorted(bindings.items()):
        config_path = config_dir / config_name
        # The map is real either way -- the binding names it. A missing config
        # means the server's exec is a no-op on that map, so inventory it and
        # say so rather than dropping it back out of sight.
        found.maps.setdefault(map_name, [])
        if not config_path.is_file():
            found.unresolved_bindings.append(
                f"{map_name} -> {display_path(config_path, root)}"
            )
            continue
        found.maps[map_name].append(display_path(config_path, root))
        configs_for.setdefault(config_path, []).append(map_name)

    for config_path, map_names in sorted(configs_for.items()):
        announced = {
            name.lower()
            for name in ANNOUNCED_MAP.findall(
                config_path.read_text(encoding="utf-8-sig", errors="replace")
            )
        }
        if announced and not announced & set(map_names):
            found.announcement_mismatches.append(
                f"{display_path(config_path, root)}: announces {'/'.join(sorted(announced))}, "
                f"bound to {', '.join(map_names)}"
            )

    referenced = {path.name for path in configs_for}
    found.unreferenced_configs = sorted(
        display_path(path, root)
        for path in config_dir.glob("ktp_*.cfg")
        if path.name not in referenced
    )
    return found


def readiness_status(entry: dict[str, Any], minimum_synthetic: int,
                     minimum_human: int) -> str:
    reviewed = all(entry.get(field) is True for field in REVIEW_FIELDS)
    human = entry.get("human_matches")
    if reviewed and human is not None and int(human) >= minimum_human:
        return "competitive_ready"
    if reviewed and int(entry.get("synthetic_matches", 0)) >= minimum_synthetic:
        return "synthetic_ready"
    return "blocked"


def build_registry(config: dict[str, Any], config_dir: Path,
                   maps_ini: Path | None = None,
                   root: Path = ROOT,
                   human_matches: dict[str, int] | None = None) -> dict[str, Any]:
    found = discover_configs(config_dir, maps_ini or (root / DEFAULT_MAPS_INI), root)
    discovered = found.maps
    errors = found.errors
    for where in hand_entered_human_matches(config):
        errors.append(f"{where}: human_matches is derived from ktp_capture_manifests, never hand-entered")
    defaults = config.get("defaults") or {}
    overrides = config.get("maps") or {}
    minimum_synthetic = int(config.get("minimum_synthetic_matches", 5))
    minimum_human = int(config.get("minimum_human_matches", 20))
    maps: list[dict[str, Any]] = []

    unknown_overrides = sorted(set(overrides) - set(discovered))
    for map_name in unknown_overrides:
        errors.append(f"registry override names a map with no match-config binding: {map_name}")

    for map_name, config_paths in discovered.items():
        entry = dict(defaults)
        entry.update(overrides.get(map_name) or {})
        entry["map_name"] = map_name
        entry["match_configs"] = config_paths
        # Unknown, not zero, when nothing was counted: a zero reads as a measurement.
        entry["human_matches"] = None if human_matches is None else human_matches.get(map_name, 0)
        entry["status"] = readiness_status(entry, minimum_synthetic, minimum_human)

        spatial_config = entry.get("spatial_config")
        if spatial_config:
            spatial_path = root / str(spatial_config)
            if not spatial_path.is_file():
                errors.append(f"{map_name}: spatial config does not exist: {spatial_config}")
            else:
                spatial = read_json(spatial_path)
                if str(spatial.get("map_name", "")).lower() != map_name:
                    errors.append(
                        f"{map_name}: spatial config declares map_name={spatial.get('map_name')!r}"
                    )
        elif entry["status"] != "blocked":
            errors.append(f"{map_name}: {entry['status']} map has no spatial_config")

        maps.append(entry)

    maps.sort(key=lambda item: (
        item.get("priority") is None,
        item.get("priority") if item.get("priority") is not None else 9999,
        item["map_name"],
    ))
    counts = {
        status: sum(1 for item in maps if item["status"] == status)
        for status in ("competitive_ready", "synthetic_ready", "blocked")
    }
    return {
        "schema_version": 2,
        "minimum_synthetic_matches": minimum_synthetic,
        "minimum_human_matches": minimum_human,
        "human_matches_source": "ktp_capture_manifests" if human_matches is not None else None,
        "valid": not errors,
        "errors": errors,
        "counts": counts,
        "maps": maps,
        # Reported, not fatal: these are pre-existing config-tree drift, not
        # spatial-readiness failures. Listing them keeps the drift visible
        # without turning this gate red on something it does not own.
        "unresolved_bindings": found.unresolved_bindings,
        "unreferenced_configs": found.unreferenced_configs,
        "announcement_mismatches": found.announcement_mismatches,
    }


def mark(value: Any) -> str:
    return "yes" if value is True else "no"


def render_markdown(registry: dict[str, Any]) -> str:
    lines = [
        "# Spatial map readiness",
        "",
        f"Registry validation: **{'PASS' if registry['valid'] else 'FAIL'}**",
        "",
        "A map is `synthetic_ready` only after its overview, flags, objective topology, and bot waypoints are reviewed and at least "
        f"{registry['minimum_synthetic_matches']} synthetic matches exist. `competitive_ready` additionally requires at least "
        f"{registry['minimum_human_matches']} human matches. Blocked maps must not inherit Anzio geometry or weights.",
        "",
        "Human matches are counted from `ktp_capture_manifests`, never hand-entered."
        if registry.get("human_matches_source") else
        "Human matches were not counted (no --database), so no map can be `competitive_ready` in this report.",
        "",
        "| Map | Status | Overview | Flags | Topology | Bot waypoints | Bot matches | Human matches | KTP configs |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in registry["maps"]:
        lines.append(
            "| {map_name} | {status} | {overview} | {flags} | {topology} | {waypoints} | {synthetic} | {human} | {configs} |".format(
                map_name=item["map_name"],
                status=item["status"],
                overview=mark(item.get("overview_transform_reviewed")),
                flags=mark(item.get("flag_geometry_reviewed")),
                topology=mark(item.get("objective_topology_reviewed")),
                waypoints=mark(item.get("bot_waypoints_verified")),
                synthetic=int(item.get("synthetic_matches", 0)),
                human="—" if item.get("human_matches") is None else int(item["human_matches"]),
                configs="<br>".join(item["match_configs"]),
            )
        )
    priority = [item for item in registry["maps"] if item.get("priority") is not None]
    lines.extend(["", "## Review queue", ""])
    for item in priority:
        lines.append(f"{int(item['priority'])}. **{item['map_name']}** — {item.get('notes', '')}")
    if registry["errors"]:
        lines.extend(["", "## Validation errors", ""])
        lines.extend(f"- {error}" for error in registry["errors"])
    if registry["unresolved_bindings"]:
        lines.extend([
            "", "## Bindings whose match config is missing", "",
            "`ktp_maps.ini` binds these maps to a config file that is not in the config "
            "directory. On a host where that is also true, `exec_map_config` execs a path "
            "that does not exist, nothing reports it, and clan mode is never armed.", "",
        ])
        lines.extend(f"- {item}" for item in registry["unresolved_bindings"])
    if registry["unreferenced_configs"]:
        lines.extend([
            "", "## Match configs no map is bound to", "",
            "These exist in the config directory but no `ktp_maps.ini` section names them, "
            "so the server never execs them and no map is inventoried from them.", "",
        ])
        lines.extend(f"- {name}" for name in registry["unreferenced_configs"])
    if registry["announcement_mismatches"]:
        lines.extend([
            "", "## Stale config announcements", "",
            "Cosmetic: the `say` line names a map the config is not bound to. Nothing reads it, "
            "and discovery no longer does either — listed so the drift stays visible.", "",
        ])
        lines.extend(f"- {item}" for item in registry["announcement_mismatches"])
    lines.extend([
        "",
        "Readiness records evidence; it does not create waypoints, invent map coordinates, or infer flag weights from another map.",
        "",
    ])
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path,
        default=ROOT / "config/analytics/spatial_maps/registry.json",
    )
    parser.add_argument(
        "--config-dir", type=Path,
        default=ROOT / "config/local/dod-configs",
    )
    parser.add_argument(
        "--maps-ini", type=Path, default=ROOT / DEFAULT_MAPS_INI,
        help="KTPMatchHandler map->config bindings; the source of map discovery",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--database", help="schema holding ktp_capture_manifests; without it human_matches is not counted")
    parser.add_argument("--defaults-extra-file", type=Path, help="MySQL option file with the credentials")
    parser.add_argument("--since", help="count only manifests with event_time on or after this YYYY-MM-DD")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        counts = None
        if args.database:
            cli = MysqlCli(database=args.database, defaults_extra_file=args.defaults_extra_file)
            counts = human_match_counts(cli, args.since)
        registry = build_registry(read_json(args.registry), args.config_dir, args.maps_ini,
                                  human_matches=counts)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "spatial-map-registry.json").write_text(
            json.dumps(registry, indent=2) + "\n", encoding="utf-8"
        )
        (args.output_dir / "SPATIAL_MAP_READINESS.md").write_text(
            render_markdown(registry), encoding="utf-8"
        )
    except (OSError, ValueError, json.JSONDecodeError, MysqlCommandError) as exc:
        print(f"spatial map registry: {exc}", file=sys.stderr)
        return 2
    print(
        "spatial map registry: "
        f"{len(registry['maps'])} maps; "
        f"{registry['counts']['competitive_ready']} competitive, "
        f"{registry['counts']['synthetic_ready']} synthetic, "
        f"{registry['counts']['blocked']} blocked"
    )
    return 0 if registry["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
