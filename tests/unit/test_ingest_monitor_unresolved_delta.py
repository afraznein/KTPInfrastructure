"""Guards for the unresolved-action counter in `scripts/hlstatsx-ingest-monitor.py`.

`unresolved_actions` is a PROCESS-LIFETIME count of distinct action codes the daemon
could not resolve, reported under a 90-minute headline. It used to report whenever the
value was above zero, so one player pressing one bind to a command `dod.so` does not
implement red an hourly production alert for the rest of the daemon's life -- 24 times
over on 2026-10-26/27, against a set that had been frozen for more than a day.

The counter beside it, `sql_failed`, was already read the other way: saved state and a
delta. These tests hold the two to the same treatment, and every suppression below has a
partner asserting a genuine rise still reports -- a filter that quietly over-matches turns
this unit into a green light that means nothing.

The subtle case is a daemon restart onto a NON-zero count. The reload zeroes the set, so
the lower value describes a different daemon generation and every code in it is new to us;
reading it as an ordinary fall is what would make that silent.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hlstatsx-ingest-monitor.py"

HEALTH = ("2026-10-27 22:51:31: 10.0.0.1:27017 - KTP_HEALTH: sql_failed=0 "
          "sql_retried=0 unresolved_actions=%d")
SIGHTING = ("2026-10-27 22:49:35: 10.0.0.2:27015 - SQL_ERROR: Unresolved action "
            "'voice_bazooka' (game 'dod') is NOT in hlstats_Actions -- this event is "
            "being DISCARDED and will never reach the database.")


def _load(tmp_path):
    spec = importlib.util.spec_from_file_location("ingest_monitor", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec.loader.exec_module(mod)
    mod.STATE = str(tmp_path / "state.json")
    return mod


def _run(mod, total, sighting=False):
    """One monitor pass against a health line reporting `total`."""
    lines = [HEALTH % total] + ([SIGHTING] if sighting else [])
    out = subprocess.CompletedProcess([], 0, stdout="\n".join(lines), stderr="")
    mod.subprocess = types.SimpleNamespace(run=lambda *a, **k: out)
    findings: list[str] = []
    info: list[str] = []
    mod.check_unresolved_actions(findings, info)
    return findings, info


def test_a_frozen_tally_reports_once_and_then_stops(tmp_path):
    mod = _load(tmp_path)
    first, _ = _run(mod, 1)
    assert len(first) == 1, "a count we have never seen must be reported once"
    for _ in range(5):
        again, info = _run(mod, 1)
        assert again == [], "a frozen lifetime count must not re-report every hour"
    assert any("unchanged since the last check" in i for i in info), \
        "staying quiet must not mean going invisible -- the value belongs in the output"


def test_but_a_rise_still_reports(tmp_path):
    """Partner to the suppression above: the delta must not be swallowed."""
    mod = _load(tmp_path)
    _run(mod, 1)
    findings, _ = _run(mod, 2)
    assert len(findings) == 1
    assert "1 new unresolved action" in findings[0]


def test_a_restart_onto_a_non_zero_count_reports(tmp_path):
    """The subtle case: 4 -> 1 is a NEW code in a new generation, not a fall."""
    mod = _load(tmp_path)
    _run(mod, 4)
    findings, info = _run(mod, 1)
    assert len(findings) == 1, "a reset baseline must not hide the codes hit since it"
    assert "1 new unresolved action" in findings[0]
    assert any("counter reset" in i for i in info)


def test_a_restart_onto_zero_is_quiet(tmp_path):
    mod = _load(tmp_path)
    _run(mod, 4)
    findings, info = _run(mod, 0)
    assert findings == []
    assert any("counter reset" in i for i in info)
    assert not any("unchanged" in i for i in info), "there is nothing left to describe"


def test_zero_is_never_a_finding(tmp_path):
    mod = _load(tmp_path)
    assert _run(mod, 0)[0] == []
    assert _run(mod, 0)[0] == []


def test_the_code_is_named_when_its_first_sighting_is_in_the_window(tmp_path):
    mod = _load(tmp_path)
    findings, _ = _run(mod, 1, sighting=True)
    assert "voice_bazooka" in findings[0], \
        "the whole complaint about this alert was that it could not say what it meant"


def test_and_says_so_plainly_when_it_cannot_name_the_code(tmp_path):
    """The daemon logs a first sighting only, so an older code is genuinely unnameable."""
    mod = _load(tmp_path)
    findings, _ = _run(mod, 1, sighting=False)
    assert "cannot" in findings[0] and "named from it" in findings[0]
    assert "voice_bazooka" not in findings[0]


def test_it_no_longer_tells_the_operator_to_seed_the_table(tmp_path):
    """`voice_bazooka` is a player's bind; seeding it would invent a row for a command
    no `dod.so` implements. The old text prescribed exactly that."""
    mod = _load(tmp_path)
    findings, _ = _run(mod, 1, sighting=True)
    assert "Seed the table" not in findings[0]
    assert "must NOT be seeded" in findings[0]


def test_the_sql_failed_counter_is_untouched_by_this_change(tmp_path):
    """Control: the two counters share a state file, so a merge bug would show here."""
    mod = _load(tmp_path)
    _run(mod, 1)
    import json
    with open(mod.STATE) as fh:
        state = json.load(fh)
    assert state["unresolved_actions"] == 1
    assert "sql_failed" in state, "the sql_failed leg must still have written its own key"
