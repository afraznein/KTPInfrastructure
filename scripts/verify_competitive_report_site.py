#!/usr/bin/env python3
"""Verify integrity, navigation, and privacy boundaries of a report site."""

from __future__ import annotations

import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


FORBIDDEN_KEYS = {
    "player_id", "steam_id", "victim_id", "attacker_id", "killer_id",
    "heatmap", "heatmap_cells", "cell_x", "cell_y", "pos_x", "pos_y", "pos_z",
    "nearest_flag", "nearest_flag_name", "flag_breakdown", "player_route", "path",
}


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        key = "href" if tag == "a" else "src" if tag in {"img", "script"} else None
        if key and values.get(key):
            self.links.append(str(values[key]))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def private_key_paths(value: Any, location: str = "root") -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in FORBIDDEN_KEYS:
                found.append(f"{location}.{key}")
            found.extend(private_key_paths(child, f"{location}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(private_key_paths(child, f"{location}[{index}]"))
    return found


def verify(root: Path) -> list[str]:
    root = root.resolve()
    errors = []
    manifest_path = root / "artifact-manifest.json"
    if not manifest_path.is_file():
        return ["artifact-manifest.json is missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    listed = set()
    for item in manifest["files"]:
        relative = item["path"]
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            errors.append(f"manifest path escapes artifact: {relative}")
            continue
        listed.add(relative)
        if not path.is_file():
            errors.append(f"manifest file missing: {relative}")
        elif path.stat().st_size != item["bytes"]:
            errors.append(f"size mismatch: {relative}")
        elif sha256(path) != item["sha256"]:
            errors.append(f"checksum mismatch: {relative}")
    actual = {
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file() and path != manifest_path
    }
    for relative in sorted(actual - listed):
        errors.append(f"unlisted file: {relative}")
    for relative in sorted(listed - actual):
        errors.append(f"listed file absent: {relative}")

    index_path = root / "index.html"
    parser = Links()
    parser.feed(index_path.read_text(encoding="utf-8"))
    for link in parser.links:
        if link.startswith(("#", "http://", "https://", "mailto:", "data:")):
            continue
        target = (root / link.split("#", 1)[0]).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            errors.append(f"HTML link escapes artifact: {link}")
            continue
        if not target.is_file():
            errors.append(f"broken HTML link: {link}")

    match_files = sorted((root / "data" / "matches").glob("*/*.json"))
    if len(match_files) != 65:
        errors.append(f"expected 65 public match files, found {len(match_files)}")
    for path in match_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        leaks = private_key_paths(payload)
        if leaks:
            errors.append(f"{path.relative_to(root)} private keys: {', '.join(leaks[:5])}")
    private_files = [path for path in root.rglob("*") if path.is_file() and ".private." in path.name]
    if private_files:
        errors.append(f"private working files included: {len(private_files)}")
    contact_sheets = list((root / "spatial").glob("*/99-atlas-contact-sheet.png"))
    if len(contact_sheets) != 13:
        errors.append(f"expected 13 contact sheets, found {len(contact_sheets)}")
    map_reports = list((root / "maps").glob("*/REPORT.md"))
    if len(map_reports) != 13:
        errors.append(f"expected 13 map reports, found {len(map_reports)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site_root", type=Path)
    args = parser.parse_args()
    errors = verify(args.site_root)
    if errors:
        print("FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PASS: manifest, links, 65 public matches, 13 map reports/atlases, privacy boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
