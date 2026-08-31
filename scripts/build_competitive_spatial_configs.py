#!/usr/bin/env python3
"""Build dataset-scoped spatial configs from captured flags and DoD overviews.

The generated files are evidence artifacts, not reviewed accumulation weights.
They contain only map geometry, objective locations, and captured initial owners;
no player coordinates or identifiers are read or emitted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import struct
from collections import defaultdict
from pathlib import Path


TABLES = {"ktp_flag_positions", "ktp_flag_state_events", "ktp_flag_captures"}
INSERT_RE = re.compile(r"^INSERT INTO `([^`]+)` \((.*?)\) VALUES \((.*)\);$")
OVERVIEW_RE = {
    "zoom": re.compile(r"\bZOOM\s+([-+0-9.]+)", re.IGNORECASE),
    "origin": re.compile(
        r"\bORIGIN\s+([-+0-9.]+)\s+([-+0-9.]+)(?:\s+[-+0-9.]+)?",
        re.IGNORECASE,
    ),
    "rotated": re.compile(r"\bROTATED\s+([01])", re.IGNORECASE),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path: Path):
    with path.open("rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = INSERT_RE.match(line.rstrip("\r\n"))
            if not match or match.group(1) not in TABLES:
                continue
            table, columns_text, tuple_text = match.groups()
            columns = [part.strip().strip("`") for part in columns_text.split(",")]
            values = next(
                csv.reader([tuple_text], delimiter=",", quotechar="'", escapechar="\\")
            )
            if len(columns) != len(values):
                raise ValueError(f"{path}: {table} column/value mismatch")
            value = {
                key: None if raw.strip().upper() == "NULL" else raw.strip()
                for key, raw in zip(columns, values)
            }
            yield table, value


def overview_geometry(text_path: Path, bitmap_path: Path) -> dict:
    text = "\n".join(
        line.split("//", 1)[0]
        for line in text_path.read_text(encoding="utf-8", errors="replace").splitlines()
    )
    zoom = OVERVIEW_RE["zoom"].search(text)
    origin = OVERVIEW_RE["origin"].search(text)
    rotated = OVERVIEW_RE["rotated"].search(text)
    if not (zoom and origin and rotated):
        raise ValueError(f"could not parse overview geometry: {text_path}")
    with bitmap_path.open("rb") as source:
        header = source.read(26)
    if len(header) < 26 or header[:2] != b"BM":
        raise ValueError(f"not a BMP overview: {bitmap_path}")
    width, height = struct.unpack_from("<ii", header, 18)
    return {
        "origin_x": float(origin.group(1)),
        "origin_y": float(origin.group(2)),
        "zoom": float(zoom.group(1)),
        "rotated": rotated.group(1) == "1",
        "width": abs(width),
        "height": abs(height),
    }


def display_name(map_name: str) -> str:
    return map_name.removeprefix("dod_").replace("_", " ").title()


def fixture_paths(dataset_root: Path, map_item: dict) -> list[Path]:
    return [
        dataset_root / fixture["files"]["hlstatsx-fixture.sql"]["path"]
        for fixture in map_item["fixtures"]
    ]


def captured_flags(paths: list[Path], map_name: str) -> tuple[list[dict], dict]:
    positions: dict[int, set[tuple[str, float, float]]] = defaultdict(set)
    owners: dict[int, set[int]] = defaultdict(set)
    capture_names: set[str] = set()
    for path in paths:
        for table, row in rows(path):
            if row.get("map_name") not in (None, map_name):
                continue
            if table == "ktp_flag_positions":
                positions[int(row["flag_index"])].add(
                    (row["flag_name"], float(row["origin_x"]), float(row["origin_y"]))
                )
            elif table == "ktp_flag_state_events" and row.get("is_initial") == "1":
                owners[int(row["flag_index"])].add(int(row["owner_team"]))
            elif table == "ktp_flag_captures" and row.get("flag_name"):
                capture_names.add(row["flag_name"])
    if not positions:
        raise ValueError(f"{map_name}: no captured flag positions")
    inconsistent = {index: values for index, values in positions.items() if len(values) != 1}
    if inconsistent:
        raise ValueError(f"{map_name}: inconsistent flag positions: {inconsistent}")
    owner_conflicts = {index: values for index, values in owners.items() if len(values) > 1}
    if owner_conflicts:
        raise ValueError(f"{map_name}: inconsistent initial owners: {owner_conflicts}")
    flags = []
    position_names = set()
    for index in sorted(positions):
        name, x, y = next(iter(positions[index]))
        position_names.add(name.casefold())
        flags.append({
            "index": index,
            "name": name,
            "code": name,
            "x": x,
            "y": y,
            "initial_owner": next(iter(owners.get(index, {0}))),
        })
    unmatched = sorted(name for name in capture_names if name.casefold() not in position_names)
    evidence = {
        "fixtures_checked": len(paths),
        "flag_count": len(flags),
        "initial_owner_flags": sum(flag["initial_owner"] in (1, 2) for flag in flags),
        "capture_names": sorted(capture_names),
        "unmatched_capture_names": unmatched,
    }
    return flags, evidence


def apply_reviewed_flags(flags: list[dict], reviewed_path: Path) -> tuple[list[dict], dict]:
    reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
    by_code = {str(flag["code"]).casefold(): flag for flag in reviewed.get("flags", [])}
    updated = []
    applied = 0
    for captured in flags:
        known = by_code.get(str(captured["code"]).casefold())
        if known is None:
            updated.append(captured)
            continue
        if (float(known["x"]), float(known["y"])) != (captured["x"], captured["y"]):
            raise ValueError(
                f"{reviewed_path}: reviewed/captured coordinates disagree for {captured['code']}"
            )
        updated.append({
            **captured,
            "name": known.get("name", captured["name"]),
            "initial_owner": int(known.get("initial_owner", captured["initial_owner"])),
        })
        applied += 1
    return updated, {
        "reviewed_config_sha256": sha256(reviewed_path),
        "reviewed_flag_overrides": applied,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("overview_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--reviewed-config-dir", type=Path)
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    overview_dir = args.overview_dir.resolve()
    output_dir = args.output_dir.resolve()
    reviewed_dir = args.reviewed_config_dir.resolve() if args.reviewed_config_dir else None
    dataset = json.loads((dataset_root / "dataset.json").read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = {}
    analysis = {
        "grid_size_units": 256.0,
        "sample_seconds": 5.0,
        "objective_radius_units": 512.0,
        "nearest_sample_seconds": 3.0,
        "isolation_radius_units": 768.0,
        "trade_seconds": 5.0,
        "multikill_seconds": 5.0,
        "opening_seconds": 45.0,
        "event_window_seconds": 30.0,
        "target_cell_minimum_seconds": 15.0,
        "corpus_cell_minimum_seconds": 60.0,
        "recurring_lane_minimum": 3,
    }
    for map_name, map_item in dataset["maps"].items():
        text_path = overview_dir / f"{map_name}.txt"
        bitmap_path = overview_dir / f"{map_name}.bmp"
        if not text_path.is_file() or not bitmap_path.is_file():
            raise FileNotFoundError(f"{map_name}: overview TXT/BMP pair is missing")
        paths = fixture_paths(dataset_root, map_item)
        flags, evidence = captured_flags(paths, map_name)
        reviewed_evidence = {}
        reviewed_path = reviewed_dir / f"{map_name}.json" if reviewed_dir else None
        if reviewed_path and reviewed_path.is_file():
            flags, reviewed_evidence = apply_reviewed_flags(flags, reviewed_path)
        config = {
            "schema_version": 1,
            "map_name": map_name,
            "display_name": display_name(map_name),
            "scope": "dataset_scoped_spatial_rendering_not_accumulation_calibration",
            "source": {
                "dataset_id": dataset["dataset_id"],
                "overview_txt_sha256": sha256(text_path),
                "overview_bmp_sha256": sha256(bitmap_path),
                **evidence,
                **reviewed_evidence,
            },
            "overview": overview_geometry(text_path, bitmap_path),
            "analysis": analysis,
            "flags": flags,
        }
        target = output_dir / f"{map_name}.json"
        target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        generated[map_name] = {
            "config": target.name,
            "overview_bmp": str(bitmap_path),
            "flags": len(flags),
            "known_initial_owners": evidence["initial_owner_flags"],
            "unmatched_capture_names": evidence["unmatched_capture_names"],
        }
    (output_dir / "registry.json").write_text(
        json.dumps({"schema_version": 1, "dataset_id": dataset["dataset_id"], "maps": generated}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {len(generated)} dataset-scoped spatial configs: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
