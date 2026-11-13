"""A correlated lookup into a MyISAM hlstats_Events_* table must be index-usable.

`BINARY a = BINARY b` cannot use an index on a `_ci` column, so inside a
correlated subquery it turns every outer row into a scan of the whole table.
On MyISAM that scan holds a table read lock, and the stats daemon's frag
UPDATE waits behind it without reading its UDP socket: one report's
death_group query held it for 317 s and the daemon dropped 623 datagrams.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ANALYTICS = Path(__file__).resolve().parents[2] / "sql" / "analytics"
BINARY_EQ = re.compile(r"BINARY\s+([\w.{}]+)\s*=\s*BINARY\s+([\w.{}]+)")


def exists_blocks(sql: str) -> list[str]:
    blocks = []
    for m in re.finditer(r"EXISTS\s*\(", sql):
        depth, i = 1, m.end()
        while depth and i < len(sql):
            depth += {"(": 1, ")": -1}.get(sql[i], 0)
            i += 1
        blocks.append(sql[m.end():i - 1])
    return blocks


def unpaired_binary_equalities(text: str) -> list[str]:
    missing = []
    for a, b in BINARY_EQ.findall(text):
        plain = re.compile(
            rf"(?<!BINARY )(?<![\w.]){re.escape(a)}\s*=\s*{re.escape(b)}(?![\w.])")
        if not plain.search(text):
            missing.append(f"{a} = {b}")
    return missing


def strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def correlated_events_lookups():
    for path in sorted(ANALYTICS.glob("*.sql")):
        for block in exists_blocks(strip_comments(path.read_text(encoding="utf-8"))):
            if "hlstats_Events_" in block:
                yield path.name, block


def test_the_scan_finds_the_death_group_lookup():
    assert "death_group_link_fact.sql" in {name for name, _ in correlated_events_lookups()}


@pytest.mark.parametrize("name,block", list(correlated_events_lookups()))
def test_binary_match_tests_in_events_lookups_are_paired(name, block):
    assert unpaired_binary_equalities(block) == [], name


def test_death_group_query_pairs_every_binary_match_test():
    sql = strip_comments((ANALYTICS / "death_group_link_fact.sql").read_text(encoding="utf-8"))
    assert len(BINARY_EQ.findall(sql)) == 5
    assert unpaired_binary_equalities(sql) == []


def test_an_unpaired_binary_test_is_reported():
    assert unpaired_binary_equalities("WHERE BINARY pf.m = BINARY ae.m") == ["pf.m = ae.m"]
    assert unpaired_binary_equalities(
        "WHERE pf.m = ae.m AND BINARY pf.m = BINARY ae.m") == []
