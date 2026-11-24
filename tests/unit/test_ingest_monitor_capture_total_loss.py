"""Guards for the total-capture-loss check in `scripts/hlstatsx-ingest-monitor.py`.

A half where `daemon_rejected == daemon_received` on its streams produced real
gameplay and stored none of it, and no aggregate can see that: fleet-wide rejection
runs at 0.87% on the worst server and 0.01% elsewhere, so two dead halves and
ordinary noise average identically. Nine such halves went unnoticed between
2026-08-26 and 2026-10-24.

Every suppression below has a partner asserting the real case still reports. The
expensive mistake in either direction is the same one: a floor above the observed
range alerts on nothing, and a floor at 1 pages on a one-second boundary race the
estate has already measured as worth one event.

The rows here are the shapes measured on production, not invented ones.
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


def _run(rows):
    """One pass of the check over rows shaped as `q()` returns them: all strings."""
    mod = _load()
    captured = {}

    def fake_q(db, sql):
        captured["sql"] = sql
        return [[str(c) for c in r] for r in rows]

    mod.q = fake_q
    findings: list[str] = []
    mod.check_capture_total_loss("hlstatsx", 90, findings)
    return findings, captured["sql"]


# server_id, match_id, half, lost, streams, events_lost, marker_stamp, iv_start,
# iv_end, iv_present -- the column order the query selects.
REUSED_ID = [16, "1.3-confirm-NY1", 1, 13, 18, 12015, "2026-10-24 18:44:52",
             "2026-02-28 23:29:34", "2026-02-28 23:49:54", 1]
REPLAYED_HALF = [6, "1.3-6755-DAL1", 1, 5, 11, 7128, "2026-09-07 22:40:40",
                 "2026-09-07 21:56:06", "2026-09-07 22:16:20", 1]
BOUNDARY_RACE = [2, "1791512565-ATL2", 1, 1, 17, 1, "2026-10-08 22:38:05",
                 "2026-10-08 22:23:01", "2026-10-08 22:38:04", 1]


def test_a_reused_match_id_reports_and_names_both_clocks():
    """The 2026-10-24 case. The finding is useless without the two timestamps:
    side by side they say "reused id", and that is the whole diagnosis."""
    findings, _ = _run([REUSED_ID])
    assert len(findings) == 1
    f = findings[0]
    assert "1.3-confirm-NY1 h1" in f and "server 16" in f
    assert "13 of 18 streams" in f and "12015 events" in f
    assert "2026-10-24 18:44:52" in f, "the half's own marker stamp must be named"
    assert "2026-02-28 23:29:34" in f, "the stale interval must be named beside it"
    assert "earlier run" in f


def test_a_replayed_half_reports_too():
    """Same mechanism, no id reuse: half 1 played twice and the upsert kept the
    first window. A check that only caught the reused-id spelling would miss the
    one shape nothing refuses."""
    findings, _ = _run([REPLAYED_HALF])
    assert len(findings) == 1
    assert "1.3-6755-DAL1 h1" in findings[0]
    assert "2026-09-07 22:16:20" in findings[0]


def test_the_one_second_boundary_race_does_not_report():
    """Measured: one stream, one event, an interval closed one second before the
    marker. A floor of 1 pages on this; a floor of 2 does not."""
    findings, _ = _run([BOUNDARY_RACE])
    assert findings == []


def test_but_the_floor_is_not_so_high_that_the_real_halves_slip_under_it():
    """Partner to the suppression above, and the trap this estate has hit before:
    an alert threshold above the observed range alerts on nothing. The smallest
    real half measured lost 4 streams."""
    smallest_real = list(REPLAYED_HALF)
    smallest_real[3] = 4
    findings, _ = _run([smallest_real])
    assert len(findings) == 1
    assert "4 of 11 streams" in findings[0]


def test_a_missing_interval_row_says_so_rather_than_printing_a_blank():
    """iv_rows = 0 is a different defect from a stale interval and has to read as
    one, or the reader goes hunting a collision that never happened."""
    no_row = list(REUSED_ID)
    no_row[7], no_row[8], no_row[9] = "", "", 0
    findings, _ = _run([no_row])
    assert len(findings) == 1
    assert "no ktp_matches row" in findings[0]


def test_an_interval_that_does_contain_the_markers_refuses_to_claim_the_cause():
    """If the markers fall inside the interval the loss is something else, and
    asserting the stale-interval cause anyway would send the reader at the wrong
    mechanism with a confident sentence."""
    inside = list(REUSED_ID)
    inside[7], inside[8] = "2026-10-24 18:20:00", "2026-10-24 18:50:00"
    findings, _ = _run([inside])
    assert len(findings) == 1
    assert "NOT the stale-interval shape" in findings[0]
    assert "rejection_reasons" in findings[0]


def test_the_equality_is_what_makes_it_total_loss():
    """Partial rejection is the ordinary fleet noise this check must not fire on --
    637 of 1,713 half-groups carry at least one partially-rejecting stream. The
    SQL, not the Python, is what excludes them, so assert on the predicate."""
    _, sql = _run([])
    # The whole expression, not a substring of it: `h.daemon_received > 0` also
    # occurs in the events_lost CASE below, so asserting it alone leaves the
    # counted predicate free to drop the guard and stay green. Without the
    # non-zero receive, every stream that received nothing counts as a total loss.
    assert ("SUM(h.daemon_received > 0 AND h.daemon_rejected = h.daemon_received)"
            " lost," in sql)


def test_the_window_and_the_floor_both_reach_the_query():
    _, sql = _run([])
    assert "INTERVAL 90 MINUTE" in sql
    assert "HAVING lost >= 2" in sql
    assert "GROUP BY h.server_id, h.match_id, h.half" in sql, \
        "a group that drops server_id merges two instances' halves under one id"


def test_a_clean_window_is_silent():
    findings, _ = _run([])
    assert findings == []
