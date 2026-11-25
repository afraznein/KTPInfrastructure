"""Guards for three ingest-monitor legs in `scripts/hlstatsx-ingest-monitor.py`:
the watched stream names, the whole-half summary comparison, and kill loss.

The fixtures are the 2026-11-24 evening as measured: ATL1 m2 h2 lost 5 damage
events and 1 kill, NY5 m2 h1 lost 2 kills and nothing flagged it, and the 90-minute
eventTime window clipped two earlier halves into false "summary ahead" lines.

Every suppression has a partner asserting the real case still reports.
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


def _rows(rows):
    return [[str(c) for c in r] for r in rows]


# --- watched stream names -------------------------------------------------------

# event_type, rows in the last week -- the shape of the production table, which
# carries `frag` and has never carried `frag_context`.
PRESENT = [("damage", 186), ("frag", 186), ("life", 186), ("position", 186)]


def _presence(rows):
    mod = _load()
    captured = {}

    def fake_q(db, sql):
        captured["sql"] = sql
        return _rows(rows)

    mod.q = fake_q
    findings: list[str] = []
    info: list[str] = []
    mod.check_watched_streams_present("hlstatsx", findings, info)
    return findings, info, captured["sql"]


def test_the_gap_leg_watches_the_stream_the_producer_writes():
    mod = _load()
    assert "frag" in mod.GAP_STREAMS and "damage" in mod.GAP_STREAMS
    assert "frag_context" not in mod.GAP_STREAMS


def test_the_gap_query_names_frag_not_frag_context():
    mod = _load()
    captured = {}
    mod.q = lambda db, sql: captured.setdefault("sql", sql) and []
    mod.check_capture_sequence_gaps("hlstatsx", 90, [], [])
    assert "event_type IN ('frag', 'damage')" in captured["sql"]


def test_a_frag_gap_on_tonights_shape_reaches_the_gap_leg():
    """A frag health row with an open gap must be read, not filtered by name."""
    mod = _load()

    def fake_q(db, sql):
        if "'frag'" not in sql:
            return []
        return _rows([[1, "1795569536-ATL1", 1, "frag", 1, 380, 379]])

    mod.q = fake_q
    findings: list[str] = []
    warnings: list[str] = []
    mod.check_capture_sequence_gaps("hlstatsx", 90, findings, warnings)
    assert findings == [] and len(warnings) == 1
    assert "frag has 1 open gap(s), 380 emitted / 379 received" in warnings[0]


def test_every_watched_stream_present_is_silent():
    findings, info, _ = _presence(PRESENT)
    assert findings == [] and info == []


def test_a_watched_stream_with_no_rows_is_a_misconfiguration():
    """The exact defect: the leg watched a name with zero rows and passed."""
    rows = [r for r in PRESENT if r[0] != "frag"]
    findings, _, _ = _presence(rows)
    assert len(findings) == 1
    f = findings[0]
    assert "MISCONFIGURED" in f and "'frag'" in f
    assert "3 other stream(s) wrote 558" in f
    assert "damage, life, position" in f


def test_the_old_name_would_have_been_caught(monkeypatch):
    """Partner: put frag_context back on the watch list and the guard names it."""
    mod = _load()
    monkeypatch.setattr(mod, "GAP_STREAMS", ("frag_context", "damage"))
    mod.q = lambda db, sql: _rows(PRESENT)
    findings: list[str] = []
    mod.check_watched_streams_present("hlstatsx", findings, [])
    assert len(findings) == 1 and "'frag_context'" in findings[0]


def test_an_empty_table_is_context_not_a_misconfiguration():
    """No capture at all cannot tell a wrong name from a quiet week."""
    findings, info, _ = _presence([])
    assert findings == []
    assert len(info) == 1 and "not verified" in info[0]


def test_the_presence_window_is_a_week():
    _, _, sql = _presence(PRESENT)
    assert "INTERVAL 7 DAY" in sql
    assert "GROUP BY event_type" in sql


# --- whole-half summary comparison ----------------------------------------------

# match_id, half, frags in the clipped eventTime window, frags for the whole half,
# ktp_match_stats kills. Measured at 22:01 on 2026-11-24.
CLIPPED = [("1795569536-ATL1", 1, 157, 379, 379),
           ("1795569946-NY5", 1, 231, 306, 306)]


def _aggregate(halves):
    """Answer the aggregate query the way MySQL would for the SQL it is given: an
    eventTime-windowed count sees the clipped figure, a whole-half count the full
    one, and only halves whose counts disagree come back."""
    mod = _load()
    captured = {}

    def fake_q(db, sql):
        captured["sql"] = sql
        clipped = "eventTime >" in sql
        out = []
        for mid, half, part, whole, kills in halves:
            frags = part if clipped else whole
            if frags != kills:
                out.append([mid, half, frags, kills])
        return _rows(out)

    mod.q = fake_q
    findings: list[str] = []
    info: list[str] = []
    mod.check_aggregate_vs_events("hlstatsx", 90, findings, info)
    return findings, info, captured["sql"]


def test_halves_that_started_before_the_window_are_not_clipped():
    findings, info, _ = _aggregate(CLIPPED)
    assert findings == []
    assert info == [], "a clipped half read as a summary running ahead"


def test_a_real_short_summary_still_reports():
    """Partner: a whole half whose summary is short is still a finding."""
    findings, _, _ = _aggregate([("1795569536-ATL1", 1, 157, 379, 378)])
    assert len(findings) == 1
    assert "summary is SHORT of its events: 1795569536-ATL1 h1 -- 379 frags" in findings[0]


def test_a_summary_ahead_of_a_whole_half_is_still_context():
    _, info, _ = _aggregate([("1795569536-ATL1", 1, 157, 370, 379)])
    assert len(info) == 1 and "370 frags, 379 kills" in info[0]


def test_the_query_selects_halves_by_end_and_counts_them_whole():
    _, _, sql = _aggregate([])
    assert "end_time > NOW() - INTERVAL 90 MINUTE" in sql
    assert "eventTime" not in sql
    assert "f.match_id = m.match_id COLLATE utf8mb4_unicode_ci" in sql
    assert "HAVING frags <> kills" in sql


# --- kill loss ------------------------------------------------------------------

# server_id, match_id, half, frag-stream emitted, hlstats_Events_Frags rows.
ATL1_M2_H1 = [1, "1795572626-ATL1", 1, 361, 361]    # positive control: no loss
ATL1_M2_H2 = [1, "1795572626-ATL1", 2, 354, 353]    # 1 kill lost
NY5_M2_H1 = [20, "1795572811-NY5", 1, 347, 345]     # 2 kills lost, unflagged
BACKLOG = [1, "1.3-7246-ATL1", 1, 355, 326]         # 2026-11-11: 29 lost
SURPLUS = [21, "1795396652-CHI1", 1, 203, 205]      # 2026-11-22: more rows than emitted


def _kills(rows, **kw):
    mod = _load()
    captured = {}

    def fake_q(db, sql):
        captured["sql"] = sql
        return _rows(rows)

    mod.q = fake_q
    findings: list[str] = []
    warnings: list[str] = []
    info: list[str] = []
    mod.check_kill_loss("hlstatsx", 90, findings, warnings, info, **kw)
    return findings, warnings, info, captured["sql"]


def test_a_clean_half_is_silent():
    findings, warnings, info, _ = _kills([ATL1_M2_H1])
    assert findings == [] and warnings == [] and info == []


def test_the_paged_halfs_lost_kill_is_reported():
    findings, warnings, _, _ = _kills([ATL1_M2_H2])
    assert findings == []
    assert len(warnings) == 1
    assert "1795572626-ATL1 h2 on server 1 -- 354 kill(s) emitted, 353 frag rows, 1 lost" \
        in warnings[0]


def test_the_unflagged_ny5_loss_is_reported():
    findings, warnings, _, _ = _kills([NY5_M2_H1])
    assert findings == [] and len(warnings) == 1
    assert "1795572811-NY5 h1 on server 20" in warnings[0] and "2 lost" in warnings[0]


def test_three_lost_kills_page():
    """Partner to the warnings above: the ceiling is the gap leg's 2, so 3 pages."""
    three = [20, "1795572811-NY5", 1, 347, 344]
    findings, warnings, _, _ = _kills([three])
    assert warnings == [] and len(findings) == 1
    assert "KILL LOSS: 1795572811-NY5 h1 on server 20" in findings[0]
    assert "emitted 347 kills" in findings[0] and "3 were never stored" in findings[0]


def test_a_backlog_half_pages():
    findings, _, _, _ = _kills([BACKLOG])
    assert len(findings) == 1 and "29 were never stored" in findings[0]


def test_more_rows_than_emitted_is_context():
    findings, warnings, info, _ = _kills([SURPLUS])
    assert findings == [] and warnings == []
    assert len(info) == 1 and "203 emitted, 205 frag rows" in info[0]


def test_the_kill_ceiling_follows_the_gap_ceiling():
    findings, warnings, _, _ = _kills([NY5_M2_H1], warn_max=1)
    assert len(findings) == 1 and warnings == []
    findings, warnings, _, _ = _kills([BACKLOG], warn_max=29)
    assert findings == [] and len(warnings) == 1


def test_the_kill_query_reads_the_frag_stream_settled_and_by_index():
    _, _, _, sql = _kills([])
    assert "event_type = 'frag'" in sql
    assert "INTERVAL 90 MINUTE" in sql
    assert "event_time <= NOW() - INTERVAL 10 MINUTE" in sql, \
        "frag rows flush on a 30 s queue, so a just-ended half under-counts"
    assert "f.match_id = h.match_id COLLATE utf8mb4_unicode_ci AND f.half = h.half" in sql
    assert "GROUP BY server_id, match_id, half" in sql


# --- tonight end to end -----------------------------------------------------------

def _main(monkeypatch, capsys, argv=()):
    mod = _load()

    def fake_q(db, sql):
        if "sequence_gap_count" in sql:
            return _rows([[1, "1795572626-ATL1", 2, "damage", 5, 679, 674]])
        if "event_type = 'frag'" in sql:
            return _rows([ATL1_M2_H1, ATL1_M2_H2, NY5_M2_H1])
        if "GROUP BY event_type" in sql:
            return _rows(PRESENT)
        return []

    mod.q = fake_q
    mod.check_udp_drops = lambda findings, info: None
    mod.check_unresolved_actions = lambda findings, info: None
    monkeypatch.setattr(sys, "argv", ["hlstatsx-ingest-monitor.py", *argv])
    rc = mod.main()
    return rc, capsys.readouterr().out


def test_tonight_pages_on_damage_and_names_both_kill_losses(monkeypatch, capsys):
    rc, out = _main(monkeypatch, capsys, ["--quiet"])
    assert rc == 1
    assert "!! capture SEQUENCE GAP: 1795572626-ATL1 h2" in out
    assert "?? kill loss (small, not paged): 1795572626-ATL1 h2" in out
    assert "?? kill loss (small, not paged): 1795572811-NY5 h1" in out
    assert "1795572626-ATL1 h1" not in out


def test_both_new_checks_run_from_main():
    src = SCRIPT.read_text(encoding="utf-8")
    main = src[src.index("def main()"):]
    assert "check_kill_loss(args.db, args.since, findings, warnings, info, args.gap_warn_max)" in main
    assert "check_watched_streams_present(args.db, findings, info)" in main
