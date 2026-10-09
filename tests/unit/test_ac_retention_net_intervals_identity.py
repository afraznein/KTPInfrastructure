"""ktp-ac-retention.sh sweep 5: ktp_net_intervals identity blanking.

The 90-day identity horizon ruled for `ktp_net_sessions` reaches the interval
table too. Every 10 s interval names its worst player per metric in a set of
`*_name` columns, so a player's name sat beside the netcode metrics forever
after the session row had dropped it. Past the same NET_IDENTITY_RETENTION_DAYS
those columns are set to NULL; the metrics and the `*_slot` columns stay.

Same harness as test_ac_retention_net_identity.py: the shipped script runs whole
under bash against a sqlite-backed fake `mysql` that emulates MySQL's
changed-rows ROW_COUNT(). The completeness property is the same one: without
the any-name-left guard a second batch re-selects already-blanked rows, counts
0 changed, and the loop stops with names still on later rows.

Not proven here: that MySQL parses the statement, or the live column list. The
list was read from information_schema on 2026-10-09 and is pinned in the shared
harness, so a change to the script's list fails here; a change to the live table
does not.
"""
import re
import sqlite3

from tests.unit.test_ac_retention_net_identity import (INTERVAL_NAME_COLUMNS, SCRIPT,
                                                       pytestmark, run_script)

__all__ = ["pytestmark"]

ALL = {c: "Name_%s" % c for c in INTERVAL_NAME_COLUMNS}
# Both sides of the horizon, and rows with only some names set: most intervals
# name a worst player for a few metrics and leave the rest NULL.
INTERVALS = [
    ("-200 days", 210.0, 3, ALL),
    ("-120 days", 95.0, 5, {"latency_worst_name": "kroD-", "jitter_worst_name": "kroD-"}),
    ("-95 days", 0.0, None, {}),
    ("-91 days", 80.0, 7, {"interp_diff_worst_name": "JustPast"}),
    ("-89 days", 70.0, 2, {"latency_worst_name": "JustInside"}),
    ("-1 days", 40.0, 1, ALL),
]


def intervals(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM ktp_net_intervals ORDER BY ts")]
    conn.close()
    return rows


def named(rows):
    return [r for r in rows if any(r[c] is not None for c in INTERVAL_NAME_COLUMNS)]


def run(tmp_path, **kw):
    return run_script(tmp_path, intervals=INTERVALS, **kw)


def test_the_script_blanks_every_name_column_the_live_table_has():
    block = re.search(r'NET_INTERVAL_NAME_COLUMNS="([^"]*)"', SCRIPT.read_text(encoding="utf-8"))
    assert block, "column list not found"
    assert tuple(block.group(1).split()) == INTERVAL_NAME_COLUMNS


def test_names_past_the_horizon_are_cleared_and_recent_ones_are_not(tmp_path):
    r = run(tmp_path)
    assert r.rc == 0, r.err
    rows = intervals(r.db)
    assert [row["latency_worst_name"] for row in named(rows)] == [
        "JustInside", ALL["latency_worst_name"]]
    for row in rows[:4]:
        assert all(row[c] is None for c in INTERVAL_NAME_COLUMNS), row


def test_metrics_and_slots_survive(tmp_path):
    r = run(tmp_path)
    kept = sorted((row["latency_worst_ms"], row["latency_worst_slot"] or 0)
                  for row in intervals(r.db))
    assert kept == sorted((lat, slot or 0) for _, lat, slot, _ in INTERVALS)


def test_the_run_counts_rows_that_carried_a_name(tmp_path):
    # Three rows past the horizon carry a name; the all-NULL one is not "blanked".
    r = run(tmp_path)
    assert "ac-retention: net_intervals identity blanked 3 row(s)" in r.out


def test_a_second_run_blanks_nothing(tmp_path):
    r = run(tmp_path, runs=2)
    assert "ac-retention: net_intervals identity blanked 0 row(s)" in r.out


def test_the_sweep_finishes_past_the_first_batch(tmp_path):
    r = run(tmp_path, env={"BATCH_SIZE": "2"})
    assert "ac-retention: net_intervals identity blanked 3 row(s)" in r.out
    assert r.sql.count("UPDATE ktp_net_intervals") >= 2
    assert len(named(intervals(r.db))) == 2


def test_zero_days_keeps_every_name(tmp_path):
    r = run(tmp_path, env={"NET_IDENTITY_RETENTION_DAYS": "0"})
    assert r.rc == 0, r.err
    assert len(named(intervals(r.db))) == 5
    assert "net_intervals identity blanking is off" in r.out
    assert "ktp_net_intervals" not in r.sql


def test_dry_run_counts_and_writes_nothing(tmp_path):
    r = run(tmp_path, env={"DRY_RUN": "1"})
    assert r.rc == 0, r.err
    assert "DRY_RUN: net_intervals identities past 90d: 3" in r.out
    assert "UPDATE ktp_net_intervals" not in r.sql
    assert len(named(intervals(r.db))) == 5


def test_dry_run_and_zero_days_touch_nothing(tmp_path):
    r = run(tmp_path, env={"DRY_RUN": "1", "NET_IDENTITY_RETENTION_DAYS": "0"})
    assert "net_intervals identity blanking is off" in r.out
    assert "ktp_net_intervals" not in r.sql


# -- mutations: each breaks the shipped sweep and names what reddens --

def _mutate(old, new):
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.count(old) == 1, "mutation anchor is not unique: %r" % old
    return text.replace(old, new)


def test_mutation_dropped_guard_reddens_the_batching_leg(tmp_path):
    """Without the any-name guard the loop stops early at BATCH_SIZE=2."""
    r = run(tmp_path, env={"BATCH_SIZE": "2"}, script_text=_mutate(
        'DAY AND (${net_interval_named})"', 'DAY"'))
    assert "ac-retention: net_intervals identity blanked 3 row(s)" not in r.out
    assert len(named(intervals(r.db))) > 2


def test_mutation_a_column_left_off_the_list_keeps_its_names(tmp_path):
    r = run(tmp_path, script_text=_mutate("\n    interp_diff_worst_name\"", "\""))
    assert intervals(r.db)[3]["interp_diff_worst_name"] == "JustPast"


def test_mutation_dropped_zero_guard_reddens(tmp_path):
    r = run(tmp_path, env={"NET_IDENTITY_RETENTION_DAYS": "0"}, script_text=_mutate(
        'if [ "${NET_IDENTITY_RETENTION_DAYS}" -gt 0 ]; then\n    batched_write',
        'if true; then\n    batched_write'))
    assert named(intervals(r.db)) == []
