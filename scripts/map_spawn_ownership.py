#!/usr/bin/env python3
"""Derive each map's AUTHORED control-point ownership from its own BSP.

Why this exists
---------------
Which team owns a flag at spawn is a property the mapper wrote into the map,
and it is readable from the shipped `.bsp` — every `dod_control_point` entity
carries a `point_default_owner` key (0 neutral / 1 allies / 2 axis). Nothing
about it needs to be inferred from play.

It was being inferred from play anyway. `map_spawn_ownership_20260908.json`
was built by watching who held each flag early in recorded matches and taking
a majority vote, which produces confidence scores instead of facts and was
wrong on 5 of 8 maps it covered (see
`SPAWN_OWNERSHIP_TABLE_CORRECTION_20260908.md`). The reason the empirical
method looked necessary is that the engine field consumers read at runtime
(`CP_owner`, i.e. `m_iTeam`) reports the CURRENT holder and is 0 for a flag no
team has taken since the last reset — so a home flag that opens owned and is
never contested reads neutral all match. The authored value lives in a
different field entirely.

This script goes to the source instead. Output is ground truth, not a vote.

What it does NOT claim
----------------------
`flag_index` is only emitted when the BSP can settle it. dodx orders control
points by ascending `point_index`, but only when EVERY control point carries a
usable one; on a map where any is absent or -1 the reorder is skipped and the
index space comes from somewhere this file cannot see (the game DLL's own
control-point master, which dodx resolves at runtime). Those maps still get
authoritative per-flag ownership keyed by NAME — which is the part that was
actually wrong — and `index_source` says so explicitly. Do not invent an order
for them from geometry; that heuristic cannot separate flags at similar depth
and has been wrong before.

Usage
-----
    python3 scripts/map_spawn_ownership.py --out artifacts/map_spawn_ownership.json
    python3 scripts/map_spawn_ownership.py --maps-dir /path/to/dod/maps --no-download

Maps are fetched from the public fastdl mirror unless a local `--maps-dir`
already holds them; downloads are cached there so a re-run is offline.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HEADER_LUMPS = 15
BSP_VERSION = 30
ENTITY_LUMP = 0
CP_CLASSNAME = "dod_control_point"
OWNER_NAMES = {0: "neutral", 1: "allies", 2: "axis"}
DEFAULT_FASTDL = "https://fastdl.ktpdod.com/dod/maps"

# The KTP competitive pool as it appears in production match history. Kept
# explicit rather than globbed from a maps directory: a directory also holds
# whatever else a server happens to have installed, and this table is consumed
# as "the maps we play".
DEFAULT_MAPS = [
    "dod_anjou_a5",
    "dod_anzio",
    "dod_anzio2_test3",
    "dod_armory_b6",
    "dod_donner",
    "dod_flash",
    "dod_halle",
    "dod_harrington",
    "dod_lennon2",
    "dod_lennon5_b1",
    "dod_railroad2_s9a",
    "dod_railyard_s9a",
    "dod_railyard_s9d",
    "dod_saints2_b2",
    "dod_saints2_b3e",
    "dod_solitude2",
    "dod_thunder2",
]


def read_entity_lump(path: Path) -> str:
    """Return the BSP's entity lump as text. Mirrors DODX_ReadBSPControlPoints."""
    with open(path, "rb") as handle:
        header = handle.read(4 + HEADER_LUMPS * 8)
        if len(header) < 4 + HEADER_LUMPS * 8:
            raise ValueError("truncated BSP header")
        version = struct.unpack_from("<i", header, 0)[0]
        if version != BSP_VERSION:
            raise ValueError(f"BSP version {version}, expected {BSP_VERSION}")
        offset, length = struct.unpack_from("<ii", header, 4 + ENTITY_LUMP * 8)
        handle.seek(offset)
        raw = handle.read(length)
    return raw.split(b"\x00", 1)[0].decode("latin-1")


def parse_entities(text: str) -> list[dict[str, str]]:
    """Split the entity lump into a list of key/value dicts."""
    entities: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        line = line.strip()
        if line == "{":
            current = {}
        elif line == "}":
            if current is not None:
                entities.append(current)
            current = None
        elif current is not None and line.startswith('"'):
            parts = line.split('"')
            # "key" "value"  ->  ['', key, ' ', value, '']
            if len(parts) >= 5:
                current[parts[1]] = parts[3]
    return entities


def as_int(raw: str, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def flag_label(entity: dict[str, str], position: int) -> str:
    """The CP's display name, preferring the same key dodx/the HUD surface."""
    for key in ("point_name", "targetname"):
        value = entity.get(key, "").strip()
        if value:
            return value
    return f"flag_{position}"


def control_points(path: Path) -> list[dict[str, object]]:
    entities = parse_entities(read_entity_lump(path))
    points = []
    for entity in entities:
        if entity.get("classname") != CP_CLASSNAME:
            continue
        owner = as_int(entity.get("point_default_owner", "0"), 0)
        if owner < 0 or owner > 2:
            # Same clamp dodx applies at its own parse site: a map-supplied
            # value outside 0..2 is nonsense and is treated as neutral rather
            # than propagated.
            owner = 0
        points.append({
            "lump_position": len(points),
            "flag_name": flag_label(entity, len(points)),
            "point_index": as_int(entity.get("point_index", "-1"), -1),
            "spawn_owner": owner,
        })
    return points


def resolve_order(points: list[dict[str, object]]) -> tuple[list[dict[str, object]], str]:
    """Order control points into the DLL's cp_index space where the BSP can.

    dodx sorts by ascending `point_index`, but only when every control point
    carries a usable one (>= 0). Otherwise it keeps entity-scan order and the
    real order is resolved at runtime from the game DLL — which this file
    cannot see, so we decline to guess.
    """
    if points and all(int(p["point_index"]) >= 0 for p in points):
        indices = [int(p["point_index"]) for p in points]
        if len(set(indices)) == len(indices):
            ordered = sorted(points, key=lambda p: int(p["point_index"]))
            for position, point in enumerate(ordered):
                point["flag_index"] = position
            return ordered, "bsp_point_index"
        return points, "duplicate_point_index"
    return points, "point_index_absent"


def fetch(map_name: str, maps_dir: Path, base_url: str, download: bool) -> Path:
    path = maps_dir / f"{map_name}.bsp"
    if path.exists():
        return path
    if not download:
        raise FileNotFoundError(path)
    maps_dir.mkdir(parents=True, exist_ok=True)
    url = f"{base_url}/{map_name}.bsp"
    with urllib.request.urlopen(url, timeout=120) as response:
        if response.status != 200:
            raise OSError(f"{url} returned {response.status}")
        path.write_bytes(response.read())
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write JSON here (default: stdout)")
    parser.add_argument("--maps-dir", type=Path,
                        default=Path(os.environ.get("KTP_MAPS_DIR", ".maps-cache")),
                        help="local BSP cache / source directory")
    parser.add_argument("--base-url", default=DEFAULT_FASTDL)
    parser.add_argument("--no-download", action="store_true",
                        help="use only maps already present in --maps-dir")
    parser.add_argument("maps", nargs="*", default=None,
                        help="map names (default: the production pool)")
    args = parser.parse_args()

    names = args.maps or DEFAULT_MAPS
    result: dict[str, object] = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "BSP entity lump, point_default_owner key",
        "authority": (
            "authored map data — not inferred from play. Supersedes any "
            "possession-derived table."
        ),
        "maps": {},
    }
    failures = 0

    for name in names:
        try:
            path = fetch(name, args.maps_dir, args.base_url, not args.no_download)
            points = control_points(path)
        except Exception as exc:                              # noqa: BLE001
            print(f"  !! {name}: {exc}", file=sys.stderr)
            result["maps"][name] = {"error": str(exc)}
            failures += 1
            continue

        if not points:
            result["maps"][name] = {"cp_count": 0, "index_source": "no_control_points",
                                    "flags": []}
            print(f"  -- {name}: no dod_control_point entities")
            continue

        ordered, index_source = resolve_order(points)
        flags = []
        for point in ordered:
            entry = {
                "flag_name": point["flag_name"],
                "spawn_owner": point["spawn_owner"],
                "spawn_owner_name": OWNER_NAMES[int(point["spawn_owner"])],
            }
            if "flag_index" in point:
                entry["flag_index"] = point["flag_index"]
            flags.append(entry)

        owned = sum(1 for f in flags if f["spawn_owner"] != 0)
        result["maps"][name] = {
            "cp_count": len(flags),
            "index_source": index_source,
            "home_flag_count": owned,
            "flags": flags,
        }
        note = "" if index_source == "bsp_point_index" else f"  [{index_source}]"
        print(f"  ok {name}: {len(flags)} CPs, {owned} authored owned{note}")

    text = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"\nwrote {args.out}")
    else:
        print(text)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
