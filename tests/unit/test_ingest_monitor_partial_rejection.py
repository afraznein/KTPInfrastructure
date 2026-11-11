"""Guards for the two interim capture alarms in `scripts/hlstatsx-ingest-monitor.py`.

A half whose start the daemon stamped late behind an ingest backlog rejects only
its go-live snapshot on each stream, so it never reaches the total-loss floor and
nothing reported it. On 2026-11-10 a 25 s backlog cost one NY1 half 282 rows over
12 streams, and the same backlog dropped 27 frag and 47 damage lines over UDP.

Every suppression here has a partner asserting the real case still reports.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hlstatsx-ingest-monitor.py"


def _load():
    spec = importlib.util.spec_from_file_location("ingest_monitor", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec.loader.exec_module(mod)
    return mod


def _run(check, rows):
    mod = _load()
    captured = {}

    def fake_q(db, sql):
        captured["sql"] = sql
        return [[str(c) for c in r] for r in rows]

    mod.q = fake_q
    findings: list[str] = []
    getattr(mod, check)("hlstatsx", 90, findings)
    return findings, captured["sql"]


F0 = "Life boundary dropped: found 0 event-time match intervals"


def _row(stream, n, sid=11, mid="1794365828-NY1", half=1, lost=0, extra=""):
    reasons = "%s=%d%s" % (F0, n, extra)
    return [sid, mid, half, stream, reasons, lost]


# The snapshot a late start costs on a 12-player, 5-flag map.
SNAPSHOT = [_row("life", 12), _row("position", 12), _row("flag_state", 5)]


def test_one_go_live_snapshot_is_not_reported():
    """The 1 s and 3 s halves: exactly the snapshot, nothing else."""
    findings, _ = _run("check_capture_partial_rejection", SNAPSHOT)
    assert findings == []


def test_more_rows_than_a_snapshot_reports():
    findings, _ = _run("check_capture_partial_rejection",
                       [_row("life", 30), _row("position", 21)])
    assert len(findings) == 1
    assert "51 rows over 2 streams" in findings[0]
    assert "1794365828-NY1 h1 on server 11" in findings[0]


def test_fifty_rows_is_still_one_snapshot():
    """Partner to the above: the floor is >50, so 50 exactly stays quiet."""
    findings, _ = _run("check_capture_partial_rejection",
                       [_row("life", 25), _row("position", 25)])
    assert findings == []


def test_more_streams_than_a_snapshot_reports():
    findings, _ = _run("check_capture_partial_rejection",
                       SNAPSHOT[:2] + [_row("flag_state", 1), _row("team_membership", 1)])
    assert len(findings) == 1
    assert "4 streams" in findings[0]


def test_the_measured_25_second_half_reports():
    rows = [_row(t, n) for t, n in (("life", 24), ("position", 24), ("flag_state", 10),
            ("team_membership", 24), ("player_state", 24), ("shot", 40), ("damage_applied", 30),
            ("grenade_entity", 20), ("objective_attempt", 10), ("move_census", 24),
            ("aim_vis", 40), ("break", 12))]
    findings, _ = _run("check_capture_partial_rejection", rows)
    assert len(findings) == 1
    assert "282 rows over 12 streams" in findings[0]
    assert "KTP_MATCH_START" in findings[0], "the finding names where to look"


def test_only_found_zero_rejections_count():
    """Other reasons are ordinary fleet noise and a different defect."""
    rows = [[11, "M", 1, "life", "%s=10;invalid producer context key=900" % F0, 0],
            [11, "M", 1, "position", "invalid producer context key=900", 0]]
    findings, _ = _run("check_capture_partial_rejection", rows)
    assert findings == []


def test_the_count_is_read_from_its_own_reason_not_a_neighbour():
    mod = _load()
    assert mod.found0_count("x=7;%s=12;y=3" % F0) == 12
    assert mod.found0_count("%s=12" % F0) == 12
    assert mod.found0_count("") == 0
    assert mod.found0_count(None) == 0
    assert mod.found0_count("found 0 event-time match intervals") == 0, "no count, no rows"


def test_a_total_loss_half_is_left_to_the_total_loss_check():
    """Same half reported twice trains the reader to skim one of them."""
    rows = [_row("life", 900, lost=1), _row("position", 900, lost=1), _row("shot", 40)]
    findings, _ = _run("check_capture_partial_rejection", rows)
    assert findings == []
    one_lost = [_row("life", 900, lost=1), _row("position", 40), _row("shot", 40)]
    findings, _ = _run("check_capture_partial_rejection", one_lost)
    assert len(findings) == 1, "one lost stream is under the total-loss floor, so it reports here"


def test_halves_are_kept_apart_by_server():
    rows = [_row("life", 30, sid=11), _row("position", 30, sid=12)]
    findings, _ = _run("check_capture_partial_rejection", rows)
    assert findings == []


def test_partial_query_reads_the_window_and_the_reason():
    _, sql = _run("check_capture_partial_rejection", [])
    assert "INTERVAL 90 MINUTE" in sql
    assert "LIKE '%found 0 event-time match intervals%'" in sql


# --- sequence gaps -------------------------------------------------------------

def test_any_open_frag_or_damage_gap_reports():
    findings, _ = _run("check_capture_sequence_gaps",
                       [[11, "1794365828-NY1", 1, "frag_context", 27, 332, 305]])
    assert len(findings) == 1
    f = findings[0]
    assert "frag_context still has 27 open gap(s)" in f
    assert "332 emitted / 305 received" in f


def test_a_zero_gap_row_does_not_report():
    findings, _ = _run("check_capture_sequence_gaps",
                       [[11, "M", 1, "damage", 0, 100, 100]])
    assert findings == []


def test_the_gap_query_is_scoped_to_frag_and_damage():
    _, sql = _run("check_capture_sequence_gaps", [])
    assert "event_type IN ('frag_context', 'damage')" in sql
    assert "sequence_gap_count > 0" in sql
    assert "INTERVAL 90 MINUTE" in sql


def test_both_checks_run_from_main():
    src = SCRIPT.read_text(encoding="utf-8")
    main = src[src.index("def main()"):]
    assert "check_capture_partial_rejection(args.db, args.since, findings)" in main
    assert "check_capture_sequence_gaps(args.db, args.since, findings)" in main
