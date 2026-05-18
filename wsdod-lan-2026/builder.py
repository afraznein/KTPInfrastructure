#!/usr/bin/env python3
"""WSDoD LAN 2026 page builder.

Fetches the published-CSV registration sheet, renders the Jinja2 template
at index.html, writes the rendered output to disk. Designed to be invoked
once per run (e.g. by a systemd timer every 5-15 min).

Usage:
    python3 builder.py                              # writes ./index.rendered.html
    python3 builder.py --output /var/www/lan/index.html
    python3 builder.py --dry-run                    # parse + report, don't write
    python3 builder.py --verbose                    # show parsed team data

Dependencies: jinja2 (everything else is stdlib).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
import urllib.error
import datetime
import re
from pathlib import Path
from typing import Iterable

try:
    import jinja2
except ImportError:
    sys.stderr.write(
        "FATAL: jinja2 not installed. Install with:\n"
        "  pip install jinja2\n"
    )
    sys.exit(2)


# Published-CSV URLs for the WSDoD LAN 2026 sheet ─────────────────────────
REGISTRATIONS_CSV = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRn8bMqKwDK8HfdNFQuGglHY3fibds019dp22DAoJdJ49SqUUacu8huNBqS5em4F_H_o1ogFaKtLV93"
    "/pub?output=csv"
)

USER_AGENT = "WSDoD-LAN-2026-Builder/1.0 (+KTPInfrastructure)"
FETCH_TIMEOUT_S = 15


# ── Fetch ─────────────────────────────────────────────────────────────────
def fetch_csv(url: str, *, timeout: int = FETCH_TIMEOUT_S) -> str:
    """Fetch a CSV URL and return its decoded text content.

    Raises urllib.error.URLError on transient failures; the caller decides
    whether to retry, fail open, or fail closed."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    # Google Sheets publish endpoint serves utf-8.
    return raw.decode("utf-8", errors="replace")


# ── Parse ─────────────────────────────────────────────────────────────────
def parse_registrations(csv_text: str) -> list[dict]:
    """Parse the registration CSV into a list of team dicts.

    Expected columns (column count is what we trust, header names may drift):
        0: Timestamp
        1: Team Name
        2: Team Tag
        3-9: Players 1-7 (player 1 = captain)
    """
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return []

    # Drop header row + drop blank rows (registration CSVs always trail empties).
    body = rows[1:]
    teams = []
    for row in body:
        # Pad short rows out to 10 fields.
        row = row + [""] * (10 - len(row))
        ts, name, tag = row[0].strip(), row[1].strip(), row[2].strip()
        if not name and not tag and not any(p.strip() for p in row[3:10]):
            continue  # fully blank row — trailing form padding

        players = [p.strip() or None for p in row[3:10]]

        teams.append({
            "name": name or "(unnamed)",
            "tag": tag or name or "—",
            "players": players,
            "registered_at": _format_timestamp(ts),
            "player_count": sum(1 for p in players if p),
        })
    return teams


def apply_overrides(teams: list[dict], overrides_path: Path) -> list[dict]:
    """Apply manual rename/roster overrides keyed by current team name.

    The override file is the escape hatch for when the sheet's publish stream
    isn't reflecting recent edits. Once the CSV catches up, the unmatched-key
    warning becomes the signal to delete this file."""
    if not overrides_path.is_file():
        return teams

    try:
        data = json.loads(overrides_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"WARN: overrides file unreadable, skipping: {e}\n")
        return teams

    renames = data.get("renames", {})
    if not renames:
        return teams

    matched = set()
    out = []
    for t in teams:
        key = t["name"]
        if key in renames:
            matched.add(key)
            override = renames[key]
            t = dict(t)  # shallow copy so we don't mutate
            if "name" in override:
                t["name"] = override["name"]
            if "tag" in override:
                t["tag"] = override["tag"]
            if "players" in override:
                players = [(p if p else None) for p in override["players"]]
                players = (players + [None] * 7)[:7]
                t["players"] = players
                t["player_count"] = sum(1 for p in players if p)
        out.append(t)

    unmatched = sorted(set(renames.keys()) - matched)
    if unmatched:
        sys.stderr.write(
            f"WARN: override keys with no CSV match (likely stale, "
            f"sheet has caught up — consider removing from "
            f"team_overrides.json): {unmatched}\n"
        )
    else:
        sys.stderr.write(
            f"NOTE: applied {len(matched)} override(s) from {overrides_path.name}\n"
        )
    return out


def _format_timestamp(ts: str) -> str:
    """Convert Google Forms timestamp to a period-correct stamp string.

    Inputs look like '2/22/2026 14:38:41'; outputs look like '22 FEB 2026'.
    Returns the raw string if it doesn't parse."""
    if not ts:
        return "DATE UNRECORDED"
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            dt = datetime.datetime.strptime(ts.strip(), fmt)
            return dt.strftime("%d %b %Y").upper()
        except ValueError:
            continue
    return ts.upper()


# ── Render ────────────────────────────────────────────────────────────────
def render(template_path: Path, *, teams: list[dict], schedule: list[dict],
           results: list[dict], last_updated: str) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_path.parent.as_posix()),
        autoescape=jinja2.select_autoescape(["html"]),
        keep_trailing_newline=True,
    )
    template = env.get_template(template_path.name)
    return template.render(
        teams=teams,
        schedule=schedule,
        results=results,
        last_updated=last_updated,
        total_players=sum(t["player_count"] for t in teams),
    )


# ── Main ──────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the WSDoD LAN 2026 page.")
    parser.add_argument(
        "--template",
        default=str(Path(__file__).resolve().parent / "index.html"),
        help="Jinja2 template path (default: ./index.html beside this script)",
    )
    parser.add_argument(
        "--output", "-o",
        default=str(Path(__file__).resolve().parent / "index.rendered.html"),
        help="Output path (default: ./index.rendered.html beside this script)",
    )
    parser.add_argument(
        "--registrations-url",
        default=REGISTRATIONS_CSV,
        help="Override the registrations CSV URL",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse + report, do not write output")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print parsed team data")
    args = parser.parse_args(argv)

    template_path = Path(args.template).resolve()
    if not template_path.is_file():
        sys.stderr.write(f"FATAL: template not found at {template_path}\n")
        return 2

    # Fetch + parse registrations.
    try:
        csv_text = fetch_csv(args.registrations_url)
    except (urllib.error.URLError, OSError) as e:
        sys.stderr.write(f"FATAL: registrations fetch failed: {e}\n")
        return 3
    teams = parse_registrations(csv_text)

    # Apply manual overrides if present (escape hatch for sheet-publish lag).
    overrides_path = template_path.parent / "team_overrides.json"
    teams = apply_overrides(teams, overrides_path)

    if args.verbose:
        sys.stderr.write(f"Parsed {len(teams)} teams:\n")
        for i, t in enumerate(teams, 1):
            sys.stderr.write(
                f"  {i:2d}. {t['name']!r:30s} tag={t['tag']!r:24s} "
                f"players={t['player_count']:d} reg={t['registered_at']}\n"
            )

    # Schedule + results are not yet sourced. Pass empty; the template
    # already handles the empty cases with "TRANSMISSION PENDING" stubs.
    schedule: list[dict] = []
    results: list[dict] = []

    now_est = datetime.datetime.now(
        tz=datetime.timezone(datetime.timedelta(hours=-4))  # EDT
    )
    last_updated = now_est.strftime("%d %b %Y / %H:%M EDT").upper()

    rendered = render(
        template_path,
        teams=teams,
        schedule=schedule,
        results=results,
        last_updated=last_updated,
    )

    if args.dry_run:
        sys.stderr.write(
            f"DRY-RUN: would write {len(rendered):,} bytes to "
            f"{args.output}\n"
        )
        return 0

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    sys.stderr.write(
        f"OK: rendered {len(teams)} teams to {output_path} "
        f"({len(rendered):,} bytes)\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
