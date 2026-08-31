#!/usr/bin/env python3
"""Measure portable SQL-fixture storage without claiming InnoDB disk allocation."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import statistics
import sys
import zlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
INSERT_RE = re.compile(r"^INSERT INTO `([^`]+)` \((.*?)\) VALUES \((.*)\);$")


def open_binary(path: Path):
    return gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_fixture(path: Path, match_id: str | None = None) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    table_rows: dict[str, int] = defaultdict(int)
    table_bytes: dict[str, int] = defaultdict(int)
    match_rows: dict[str, int] = defaultdict(int)
    match_bytes: dict[str, int] = defaultdict(int)
    uncompressed_bytes = 0
    uncompressed_hash = hashlib.sha256()
    gzip_compressor = zlib.compressobj(level=9, wbits=31)
    canonical_gzip_bytes = 0

    with open_binary(path) as handle:
        for raw_line in handle:
            uncompressed_bytes += len(raw_line)
            uncompressed_hash.update(raw_line)
            canonical_gzip_bytes += len(gzip_compressor.compress(raw_line))
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            parsed = INSERT_RE.match(line)
            if not parsed:
                continue
            table, columns_text, tuple_text = parsed.groups()
            table_rows[table] += 1
            table_bytes[table] += len(raw_line)
            if match_id is None:
                continue
            columns = [column.strip().strip("`") for column in columns_text.split(",")]
            if "match_id" not in columns:
                continue
            values = next(csv.reader(
                [tuple_text], delimiter=",", quotechar="'", escapechar="\\"
            ))
            if len(values) != len(columns):
                raise ValueError(f"{path.name}: malformed INSERT for {table}")
            value = values[columns.index("match_id")].strip()
            if value == match_id:
                match_rows[table] += 1
                match_bytes[table] += len(raw_line)

    canonical_gzip_bytes += len(gzip_compressor.flush())
    inserted_bytes = sum(table_bytes.values())
    return {
        "fixture": path.name,
        "container_bytes": path.stat().st_size,
        "container_sha256": sha256_file(path),
        "uncompressed_bytes": uncompressed_bytes,
        "uncompressed_sha256": uncompressed_hash.hexdigest(),
        "canonical_gzip_bytes": canonical_gzip_bytes,
        "compression_ratio": round(path.stat().st_size / uncompressed_bytes, 4)
        if uncompressed_bytes else None,
        "insert_rows": sum(table_rows.values()),
        "insert_bytes": inserted_bytes,
        "non_insert_bytes": uncompressed_bytes - inserted_bytes,
        "match_id": match_id,
        "match_tagged_rows": sum(match_rows.values()),
        "match_tagged_bytes": sum(match_bytes.values()),
        "tables": [
            {
                "table": table,
                "rows": table_rows[table],
                "sql_bytes": table_bytes[table],
                "match_tagged_rows": match_rows.get(table, 0),
                "match_tagged_bytes": match_bytes.get(table, 0),
            }
            for table in sorted(table_rows, key=lambda name: (-table_bytes[name], name))
        ],
    }


def distribution(values: list[int]) -> dict[str, float | int] | None:
    if not values:
        return None
    return {
        "count": len(values),
        "minimum": min(values),
        "mean": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
        "maximum": max(values),
    }


def build_report(target: dict[str, Any], comparisons: list[dict[str, Any]],
                 comparison_label: str) -> dict[str, Any]:
    container_distribution = distribution([item["container_bytes"] for item in comparisons])
    uncompressed_distribution = distribution([item["uncompressed_bytes"] for item in comparisons])
    gzip_distribution = distribution([item["canonical_gzip_bytes"] for item in comparisons])
    mean_gzip = gzip_distribution["mean"] if gzip_distribution else None
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "measurement": "portable_sql_fixture_not_live_database_allocation",
        "target": target,
        "comparison": {
            "label": comparison_label,
            "fixtures": comparisons,
            "container_bytes": container_distribution,
            "uncompressed_bytes": uncompressed_distribution,
            "canonical_gzip_bytes": gzip_distribution,
        },
        "projection": {
            "basis": "comparison_mean_canonical_gzip_bytes" if mean_gzip is not None else "target_canonical_gzip_bytes",
            "per_match_bytes": mean_gzip if mean_gzip is not None else target["canonical_gzip_bytes"],
            "matches": {
                str(count): round((mean_gzip if mean_gzip is not None else target["canonical_gzip_bytes"]) * count)
                for count in (10, 100, 1000)
            },
        },
        "human_baseline": {
            "available": False,
            "reason": "No reviewed human-match fixture corpus was supplied; synthetic behavior is not a real-match average.",
        },
    }


def kib(value: float | int | None) -> str:
    return "n/a" if value is None else f"{float(value) / 1024:.2f} KiB"


def render_markdown(report: dict[str, Any]) -> str:
    target = report["target"]
    comparison = report["comparison"]
    lines = [
        "# Match fixture storage report",
        "",
        "> This measures portable SQL dump bytes, not live InnoDB data/index allocation. "
        "It is exact for archiving and transfer, and only a planning proxy for database storage.",
        "",
        "## Target fixture",
        "",
        "| Measure | Value |", "|---|---:|",
        f"| Fixture container | {kib(target['container_bytes'])} |",
        f"| Uncompressed SQL | {kib(target['uncompressed_bytes'])} |",
        f"| Canonical gzip projection | {kib(target['canonical_gzip_bytes'])} |",
        f"| All INSERT payload | {kib(target['insert_bytes'])} ({target['insert_rows']} rows) |",
        f"| Match-tagged INSERT payload | {kib(target['match_tagged_bytes'])} ({target['match_tagged_rows']} rows) |",
        f"| Schema/comments/SQL framing | {kib(target['non_insert_bytes'])} |",
        "",
        f"## Comparison: {comparison['label']}",
        "",
    ]
    if comparison["container_bytes"]:
        container = comparison["container_bytes"]
        uncompressed = comparison["uncompressed_bytes"]
        compressed = comparison["canonical_gzip_bytes"]
        lines.extend([
            "| Measure | Minimum | Mean | Median | Maximum |", "|---|---:|---:|---:|---:|",
            f"| Fixture container | {kib(container['minimum'])} | {kib(container['mean'])} | "
            f"{kib(container['median'])} | {kib(container['maximum'])} |",
            f"| Uncompressed SQL | {kib(uncompressed['minimum'])} | {kib(uncompressed['mean'])} | "
            f"{kib(uncompressed['median'])} | {kib(uncompressed['maximum'])} |",
            f"| Canonical gzip | {kib(compressed['minimum'])} | {kib(compressed['mean'])} | "
            f"{kib(compressed['median'])} | {kib(compressed['maximum'])} |",
        ])
    else:
        lines.append("No comparison fixtures were supplied.")
    lines.extend([
        "", "## Largest target INSERT tables", "",
        "| Table | Rows | SQL bytes | Match-tagged rows | Match-tagged bytes |",
        "|---|---:|---:|---:|---:|",
    ])
    for item in target["tables"][:20]:
        lines.append(
            f"| `{item['table']}` | {item['rows']} | {item['sql_bytes']} | "
            f"{item['match_tagged_rows']} | {item['match_tagged_bytes']} |"
        )
    projection = report["projection"]
    lines.extend([
        "", "## Archive-size projection", "",
        f"Basis: {kib(projection['per_match_bytes'])} per match from `{projection['basis']}`.", "",
        "| Matches | Projected fixture storage |", "|---:|---:|",
    ])
    lines.extend(
        f"| {count} | {kib(value)} |" for count, value in projection["matches"].items()
    )
    lines.extend([
        "", "## Real-match comparison", "",
        "Unavailable until reviewed human fixtures exist. Bot activity, match duration, and event density "
        "must not be presented as an average competitive match. Re-run this report with the first preserved "
        "human corpus before setting retention or capacity limits.", "",
    ])
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--match-id")
    parser.add_argument("--comparison", action="append", type=Path, default=[])
    parser.add_argument("--comparison-label", default="synthetic bot corpus")
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        target = inspect_fixture(args.target, args.match_id)
        comparisons = [inspect_fixture(path) for path in args.comparison]
        report = build_report(target, comparisons, args.comparison_label)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "match-fixture-storage.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        (args.output_dir / "MATCH_FIXTURE_STORAGE.md").write_text(
            render_markdown(report), encoding="utf-8"
        )
    except (OSError, ValueError, csv.Error) as exc:
        print(f"fixture storage: {exc}", file=sys.stderr)
        return 2
    print(f"fixture storage: {kib(target['container_bytes'])}; {target['insert_rows']} INSERT rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
