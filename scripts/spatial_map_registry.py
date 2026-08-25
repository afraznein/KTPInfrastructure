#!/usr/bin/env python3
"""Inventory KTP match maps and enforce explicit spatial-readiness gates."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MAP_LINE = re.compile(
    r"^\s*say\s+KTP\s+(?:CLASSIC\s+)?(dod_[A-Za-z0-9_]+)\s+Match\s+Config\s+Executed\s*$",
    re.IGNORECASE | re.MULTILINE,
)
REVIEW_FIELDS = (
    "overview_transform_reviewed",
    "flag_geometry_reviewed",
    "objective_topology_reviewed",
    "bot_waypoints_verified",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def discover_configs(config_dir: Path, root: Path = ROOT) -> tuple[dict[str, list[str]], list[str]]:
    discovered: dict[str, list[str]] = {}
    errors: list[str] = []
    for path in sorted(config_dir.glob("ktp_*.cfg")):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        matches = MAP_LINE.findall(text)
        if len(matches) != 1:
            errors.append(
                f"{display_path(path, root)}: expected one KTP match-config map declaration, found {len(matches)}"
            )
            continue
        map_name = matches[0].lower()
        discovered.setdefault(map_name, []).append(display_path(path, root))
    if not discovered:
        errors.append(f"{display_path(config_dir, root)}: no ktp_*.cfg match configs found")
    return discovered, errors


def readiness_status(entry: dict[str, Any], minimum_synthetic: int,
                     minimum_human: int) -> str:
    reviewed = all(entry.get(field) is True for field in REVIEW_FIELDS)
    if reviewed and int(entry.get("human_matches", 0)) >= minimum_human:
        return "competitive_ready"
    if reviewed and int(entry.get("synthetic_matches", 0)) >= minimum_synthetic:
        return "synthetic_ready"
    return "blocked"


def build_registry(config: dict[str, Any], config_dir: Path,
                   root: Path = ROOT) -> dict[str, Any]:
    discovered, errors = discover_configs(config_dir, root)
    defaults = config.get("defaults") or {}
    overrides = config.get("maps") or {}
    minimum_synthetic = int(config.get("minimum_synthetic_matches", 5))
    minimum_human = int(config.get("minimum_human_matches", 20))
    maps: list[dict[str, Any]] = []

    unknown_overrides = sorted(set(overrides) - set(discovered))
    for map_name in unknown_overrides:
        errors.append(f"registry override has no discovered KTP match config: {map_name}")

    for map_name, config_paths in discovered.items():
        entry = dict(defaults)
        entry.update(overrides.get(map_name) or {})
        entry["map_name"] = map_name
        entry["match_configs"] = config_paths
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
        "schema_version": 1,
        "minimum_synthetic_matches": minimum_synthetic,
        "minimum_human_matches": minimum_human,
        "valid": not errors,
        "errors": errors,
        "counts": counts,
        "maps": maps,
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
                human=int(item.get("human_matches", 0)),
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
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        registry = build_registry(read_json(args.registry), args.config_dir)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "spatial-map-registry.json").write_text(
            json.dumps(registry, indent=2) + "\n", encoding="utf-8"
        )
        (args.output_dir / "SPATIAL_MAP_READINESS.md").write_text(
            render_markdown(registry), encoding="utf-8"
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
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
