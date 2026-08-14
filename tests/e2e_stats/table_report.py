"""Database delta capture and Markdown rendering for a Lane B match.

The base HLStatsX schema contains many configuration tables.  Reporting ten
rows from every one would bury the match data in static seed data, so this
module snapshots row counts immediately before hlds starts and reports every
table whose row count grew during the synthetic match.
"""

from __future__ import annotations

import re
from typing import Any


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def _lines(raw: str) -> list[list[str]]:
    return [line.split("\t") for line in raw.strip().splitlines() if line]


def table_counts(db) -> dict[str, int]:
    rows = _lines(db.sql("SHOW TABLES"))
    tables = [row[0] for row in rows[1:]] if rows else []
    counts: dict[str, int] = {}
    for table in tables:
        if not _IDENTIFIER.fullmatch(table):
            raise ValueError(f"unsafe table name returned by MySQL: {table!r}")
        counts[table] = db.count(f"SELECT COUNT(*) FROM `{table}`")
    return counts


def _primary_key(db, table: str) -> list[str]:
    rows = _lines(db.sql(f"SHOW KEYS FROM `{table}` WHERE Key_name='PRIMARY'"))
    if len(rows) < 2:
        return []
    header = rows[0]
    try:
        seq_idx = header.index("Seq_in_index")
        col_idx = header.index("Column_name")
    except ValueError:
        return []
    keys = sorted(rows[1:], key=lambda row: int(row[seq_idx]))
    return [row[col_idx] for row in keys]


def changed_table_samples(db, before: dict[str, int], *, limit: int = 10) -> list[dict]:
    """Return newest rows for every table whose row count increased."""
    after = table_counts(db)
    result = []
    for table in sorted(after):
        old, new = before.get(table, 0), after[table]
        if new <= old:
            continue
        keys = _primary_key(db, table)
        order = ""
        if keys:
            order = " ORDER BY " + ", ".join(f"`{key}` DESC" for key in keys)
        rows = _lines(db.sql(f"SELECT * FROM `{table}`{order} LIMIT {int(limit)}"))
        result.append({
            "table": table,
            "before": old,
            "after": new,
            "inserted": new - old,
            "order_by": keys,
            "columns": rows[0] if rows else [],
            "rows": rows[1:] if len(rows) > 1 else [],
        })
    return result


def _cell(value: Any, limit: int = 160) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_markdown(report: dict) -> str:
    emitted, rows = report.get("emitted", {}), report.get("rows", {})
    match = report.get("match") or {}
    failures = report.get("failures") or []
    gaps = report.get("coverage_gaps") or []
    status = "FAIL" if failures else ("INCOMPLETE" if gaps else "PASS")
    out = [
        "# Lane B synthetic match report",
        "",
        "| Result | Map | Match ID | Half | Play seconds | Players | Bots |",
        "|---|---|---|---:|---:|---:|---:|",
        f"| {status} | {_cell(report.get('map', ''))} | {_cell(match.get('match_id', ''))} "
        f"| {match.get('half', '')} | {report.get('play_seconds', '')} "
        f"| {rows.get('players', '')} | {rows.get('bots', '')} |",
        "",
        "## Stats summary",
        "",
        "| Stat | Emitted by game | Recorded in database |",
        "|---|---:|---:|",
        f"| Kills/frags | {emitted.get('kills', 0)} | {rows.get('frags', 0)} |",
        f"| Assists | {emitted.get('assist', 0)} | "
        f"{(rows.get('assist') or {}).get('ppa', 0)} |",
        f"| Cap breaks | {emitted.get('cap_break', 0)} | "
        f"{(rows.get('cap_break') or {}).get('pa', 0)} |",
        f"| Suicides | {emitted.get('suicide', 0)} | {rows.get('suicides', 0)} |",
        f"| Headshots | {emitted.get('headshot', 0)} | included in frag rows |",
        f"| Damage events | {emitted.get('damage', 0)} | see changed-table samples |",
        "",
        "## Assertion verdicts",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    for verdict in report.get("carried") or []:
        out.append(
            f"| {_cell(verdict.get('code', ''))} | {_cell(verdict.get('status', ''))} "
            f"| {_cell(verdict.get('detail', ''))} |"
        )
    if not report.get("carried"):
        out.append("| — | — | No verdicts were produced |")

    if failures:
        out += ["", "## Failures", ""] + [f"- {_cell(item, 500)}" for item in failures]
    if gaps:
        out += ["", "## Coverage gaps", ""] + [f"- {_cell(item, 500)}" for item in gaps]

    samples = report.get("table_samples") or []
    out += [
        "",
        "## Tables populated during this match",
        "",
        "| Table | Before | After | Inserted |",
        "|---|---:|---:|---:|",
    ]
    for sample in samples:
        out.append(
            f"| `{sample['table']}` | {sample['before']} | {sample['after']} "
            f"| +{sample['inserted']} |"
        )
    if not samples:
        out.append("| — | 0 | 0 | No inserted match rows detected |")

    for sample in samples:
        out += ["", f"### `{sample['table']}` — top {len(sample['rows'])} rows", ""]
        columns = sample["columns"]
        if not columns:
            out.append("No rows returned.")
            continue
        out.append("| " + " | ".join(_cell(col) for col in columns) + " |")
        out.append("|" + "|".join("---" for _ in columns) + "|")
        for row in sample["rows"]:
            out.append("| " + " | ".join(_cell(value) for value in row) + " |")
    return "\n".join(out) + "\n"
