#!/usr/bin/env python3
"""Emit the website's `map-geometry.json` from the deployable spatial configs.

The site's table is hand-maintained. `spatial_map_geometry.py` already derives
the same matrices, and `tests/unit/test_spatial_map_geometry.py` proves it, but
there was no way to turn the derivation back into the file the site ships -- so
the equality was a one-way proof and the hand edit stayed the only producer.

Three rules this tool exists to enforce, each one a way the obvious version is
wrong:

Only the geometry fields are written. `technical_validation` and any other key
on a descriptor are carried through byte-for-byte, because this generator has
no source for them: `registry.json` records `overview_transform_reviewed` for
`dod_anzio` alone, so minting that field would turn a derivation into a review
claim.

A configured map that the base table does not already carry is REFUSED rather
than added, for the same reason -- a new descriptor would need a
`technical_validation` value that nothing here can derive.

A map the site ships with no config here is left exactly as it is and reported
as deferred. `dod_lennon5_b1` is that map (operator ruling 2026-10-08): the
generator cannot invent an overview without captured flag positions.

Why the target is the site's deployable table and never the report payload:
report rows are immutable, so geometry delivered inside a report freezes at the
moment that report was written and can never be corrected afterwards -- and
shipped descriptors have already needed correcting once.

`--refresh-pin` is the other half of the job. Regenerating the site's table is
an upstream hand-edit as far as `PIN.json` is concerned, which its own
`drift_directions` records as NOT CAUGHT -- so the vendored copy goes stale and
the suite stays green against bytes the site no longer ships. The refresh
re-vendors upstream, rewrites the provenance fields, and sets `equality_grade`
from a comparison rather than from a claim: `generated` once upstream is
byte-identical to this emitter, `rounded` while it is still the hand-typed
table. The exact-equality gate keys on that field, so the pin move upgrades the
check instead of merely recording that someone moved it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.spatial_map_geometry import overview_matrices  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SPATIAL_MAPS = REPO / "config/analytics/spatial_maps"
REGISTRY = SPATIAL_MAPS / "registry.json"
SITE_FIXTURE_DIR = REPO / "tests/fixtures/site_map_geometry"
VENDORED = SITE_FIXTURE_DIR / "map-geometry.json"
PIN = SITE_FIXTURE_DIR / "PIN.json"

# The site's descriptor fields this generator owns. Everything else on a
# descriptor is carried through untouched.
GENERATED_FIELDS = ("geometry_version", "dimensions", "world_to_pixel",
                    "pixel_to_world")
UPSTREAM_PATH = "src/features/public-match-report/fixtures/map-geometry.json"


class UnbackedDescriptor(ValueError):
    """A map would need a field this generator cannot derive."""


def _load(path: Path) -> OrderedDict:
    return json.loads(path.read_text(encoding="utf-8-sig"),
                      object_pairs_hook=OrderedDict)


def configured_maps(registry: dict) -> OrderedDict:
    """Map name -> overview block, for every registry map with a config."""
    found: OrderedDict = OrderedDict()
    for name, entry in registry.get("maps", {}).items():
        config = entry.get("spatial_config")
        if not config:
            continue
        overview = _load(REPO / config).get("overview")
        if not overview:
            raise UnbackedDescriptor(
                f"{name}: {config} has no overview block to derive from")
        found[name] = overview
    return found


def build_table(base: OrderedDict, overviews: OrderedDict) -> tuple[OrderedDict, dict]:
    """Rewrite the geometry fields of `base` from `overviews`.

    Returns the new table and a report naming what was generated, what was left
    alone, and which fields actually moved.
    """
    unbacked = [name for name in overviews if name not in base]
    if unbacked:
        raise UnbackedDescriptor(
            "refusing to add " + ", ".join(sorted(unbacked))
            + " to the site table: a new descriptor needs a "
            "technical_validation value, and registry.json records a review "
            "for dod_anzio alone. Add the descriptor upstream first, then "
            "regenerate its geometry here.")
    table: OrderedDict = OrderedDict()
    changed: dict[str, list[str]] = {}
    for name, descriptor in base.items():
        if name not in overviews:
            table[name] = descriptor
            continue
        derived = overview_matrices(name, overviews[name])
        updated = OrderedDict(descriptor)
        moved = []
        for field in GENERATED_FIELDS:
            if field not in updated:
                raise UnbackedDescriptor(
                    f"{name}: the base descriptor has no {field}, so this is "
                    "not the table this generator was written against")
            value = derived[field]
            if isinstance(value, dict) and isinstance(updated[field], dict):
                # Keep the base's key order inside a nested block, so a
                # regeneration diffs as values rather than as a reshuffle.
                if set(value) != set(updated[field]):
                    raise UnbackedDescriptor(
                        f"{name}.{field}: the base and the derivation disagree "
                        "about which keys this block holds")
                value = OrderedDict(
                    (key, value[key]) for key in updated[field])
            if updated[field] != value:
                moved.append(field)
            updated[field] = value
        table[name] = updated
        if moved:
            changed[name] = moved
    return table, {
        "generated": sorted(overviews),
        "deferred": sorted(set(base) - set(overviews)),
        "changed_fields": changed,
        "carried_through": sorted(
            {key for descriptor in base.values() for key in descriptor}
            - set(GENERATED_FIELDS)),
    }


def serialize(table: OrderedDict) -> bytes:
    """The site file's own shape: one-space indent, LF, no trailing newline."""
    return json.dumps(table, indent=1).encode("utf-8")


def emit() -> tuple[bytes, dict]:
    table, report = build_table(_load(VENDORED), configured_maps(_load(REGISTRY)))
    return serialize(table), report


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout.strip()


def refresh_pin(upstream: Path) -> dict:
    """Re-vendor upstream's table and rewrite PIN.json's provenance."""
    raw = subprocess.run(
        ["git", "show", f"origin/main:{UPSTREAM_PATH}"], cwd=str(upstream),
        check=True, capture_output=True).stdout
    VENDORED.write_bytes(raw)
    normalized = raw.replace(b"\r\n", b"\n")
    pin = _load(PIN)
    pin["upstream_commit"] = _git(
        ["log", "-1", "--format=%H", "origin/main", "--", UPSTREAM_PATH], upstream)
    pin["upstream_commit_date"] = _git(
        ["log", "-1", "--format=%cI", pin["upstream_commit"]], upstream)
    pin["upstream_commit_subject"] = _git(
        ["log", "-1", "--format=%s", pin["upstream_commit"]], upstream)
    pin["upstream_blob"] = _git(["rev-parse", f"origin/main:{UPSTREAM_PATH}"], upstream)
    pin["bytes"] = len(normalized)
    # Owned here too: a hand-kept capture date outlives the bytes it dates and
    # then claims a capture predating upstream_commit.
    pin["captured_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pin["sha256_lf"] = hashlib.sha256(normalized).hexdigest()
    generated, _ = emit()
    pin["equality_grade"] = "generated" if generated == normalized else "rounded"
    # newline="" so this does not rewrite the whole file as CRLF on Windows.
    PIN.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8", newline="")
    return {"equality_grade": pin["equality_grade"], "bytes": pin["bytes"],
            "upstream_blob": pin["upstream_blob"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="compare the vendored copy against the emitted "
                             "table and exit 1 on any difference")
    parser.add_argument("--refresh-pin", metavar="KEEP_THE_PRAC",
                        help="re-vendor upstream's table from this checkout and "
                             "rewrite PIN.json, including equality_grade")
    parser.add_argument("--report", action="store_true",
                        help="print what was generated, deferred and carried "
                             "through instead of the table")
    args = parser.parse_args(argv)

    if args.refresh_pin:
        result = refresh_pin(Path(args.refresh_pin))
        print(json.dumps(result, indent=1))
        return 0

    generated, report = emit()
    if args.report:
        print(json.dumps(report, indent=1))
        return 0
    if args.check:
        current = VENDORED.read_bytes().replace(b"\r\n", b"\n")
        if current == generated:
            print("vendored table is byte-identical to the emitted one")
            return 0
        print("the vendored table is NOT the emitted one. Fields that move:")
        print(json.dumps(report["changed_fields"], indent=1))
        print("Deferred (no config here, left verbatim): "
              + ", ".join(report["deferred"] or ["none"]))
        return 1
    sys.stdout.write(generated.decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
