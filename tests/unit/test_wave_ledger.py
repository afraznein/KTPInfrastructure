"""ktp-wave-ledger: the post-activation CLAUDE.md row flip, as a gate.

Nothing here touches the fleet, the network, or the real ledger directory --
every case runs against a tmp_path ledger and an inline CLAUDE.md fixture.

The case that matters is `test_stale_row_blocks`: it reproduces 2026-09-01,
where a wave activated and two version rows were never flipped, and asserts the
gate refuses rather than reminding.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load():
    spec = importlib.util.spec_from_file_location(
        "ktp_wave_ledger", os.path.join(_ROOT, "scripts", "ktp-wave-ledger.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ktp_wave_ledger"] = mod
    spec.loader.exec_module(mod)
    return mod


wl = _load()

# Shaped like the real table: multi-sentence cells, a prior build named in the
# same row, and a component whose row is absent entirely.
CLAUDE_MD = """\
# KTP

| Component | Live | Since | Verified hash |
|---|---|---|---|
| KTP-ReHLDS | 3.22.0.976-dev | 08-27 | `e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0` |
| KTPAMXX | core 2.7.33 + dodx 2.7.32.5683 | 08-31 | core `a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1` \
* dodx `d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0` -- prior core `1af52525aaaaaaaaaaaaaaaaaaaaaaaa` \
is at `_fleet-backups/`. |
| KTPCvarChecker | **7.36** | 08-31 | `ce6ce034bbbbbbbbbbbbbbbbbbbbbbbb` -- backup holds 7.35. |
| KTPMatchHandler | **0.10.168** | 08-28 | `2cb28c15cccccccccccccccccccccccc` |

Prose mentioning `c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7` outside any table row.
"""

CVAR_LIVE = "c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7c7"   # 7.37 -- live, but only in prose
MH_LIVE = "70707070707070707070707070707070"     # 0.10.170 -- live, absent entirely
ENGINE_LIVE = "e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0"  # matches its row


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("KTP_WAVE_LEDGER_DIR", str(tmp_path / "waves"))


@pytest.fixture
def claude_md(tmp_path):
    p = tmp_path / "CLAUDE.md"
    p.write_text(CLAUDE_MD, encoding="utf-8")
    return str(p)


def _artifact(md5, basename="ktp_cvar.amxx", version=None):
    return {"basename": basename, "md5": md5, "version": version,
            "remote_dir": "serverfiles/dod/addons/ktpamx/plugins"}


def _stage_multi(artifacts, *, days_ago=2.0):
    staged = dt.datetime.now(dt.timezone.utc).timestamp() - days_ago * 86400
    return wl.record_wave(artifacts, hosts=["atlanta"], targets=24, staged_at=staged)


def _stage(md5, basename="ktp_cvar.amxx", *, version=None, days_ago=2.0):
    return _stage_multi([_artifact(md5, basename, version)], days_ago=days_ago)


# -- activation timing -----------------------------------------------------

@pytest.mark.parametrize("iso", [
    "2026-09-01T21:58:30-04:00",   # the real 09-01 wave
    "2026-09-02T02:59:59-04:00",   # a minute before the swap
    "2026-01-15T22:00:00-05:00",   # winter, EST
])
def test_activation_is_the_next_0300_et(iso):
    staged = dt.datetime.fromisoformat(iso).timestamp()
    got = wl.next_activation(staged)
    assert got > staged
    # Whichever tz path ran, the answer must land on 03:00 in the wave's own
    # UTC offset -- that is the property, not the implementation.
    off = dt.datetime.fromisoformat(iso).utcoffset()
    local = dt.datetime.fromtimestamp(got, dt.timezone.utc) + off
    assert (local.hour, local.minute) == (3, 0)
    assert got - staged <= 25 * 3600


def test_a_wave_staged_after_0300_waits_for_tomorrow():
    staged = dt.datetime.fromisoformat("2026-09-02T03:00:01-04:00").timestamp()
    got = wl.next_activation(staged)
    assert got - staged > 20 * 3600


def test_dst_boundary_helpers():
    assert wl._nth_sunday(2026, 3, 2) == 8      # 2026-03-08, EDT begins
    assert wl._nth_sunday(2026, 11, 1) == 1     # 2026-11-01, EST returns
    assert wl._et_offset_hours(dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)) == 4
    assert wl._et_offset_hours(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)) == 5


# -- the row assertion -----------------------------------------------------

def test_matching_row_passes():
    f = wl.check_row(CLAUDE_MD, "engine_i486.so", ENGINE_LIVE)
    assert f.ok and f.scope == "row" and f.component == "KTP-ReHLDS"


def test_md5_in_prose_does_not_satisfy_the_row():
    """The 7.37 hash IS in the file -- in a paragraph. The row still says 7.36."""
    f = wl.check_row(CLAUDE_MD, "ktp_cvar.amxx", CVAR_LIVE)
    assert not f.ok
    assert f.scope == "row"
    assert "appears elsewhere in the file but not on that row" in f.detail


def test_absent_md5_fails_and_says_the_row_was_not_flipped():
    f = wl.check_row(CLAUDE_MD, "KTPMatchHandler.amxx", MH_LIVE, version="0.10.170")
    assert not f.ok
    assert "0.10.170" in f.detail


def test_a_prior_build_named_in_the_same_row_is_not_a_pass():
    """Rows legitimately name superseded builds and backup paths. Only the
    CURRENT md5 satisfies the check."""
    prior = "1af52525aaaaaaaaaaaaaaaaaaaaaaaa"
    assert prior in CLAUDE_MD
    assert wl.check_row(CLAUDE_MD, "ktpamx_i386.so", prior).ok        # it is on the row
    # ...and the row is still wrong for a build it does not name.
    assert not wl.check_row(CLAUDE_MD, "ktpamx_i386.so", "0" * 32).ok


def test_case_insensitive_md5():
    assert wl.check_row(CLAUDE_MD, "engine_i486.so", ENGINE_LIVE.upper()).ok


def test_unmapped_basename_degrades_loudly_not_silently():
    f = wl.check_row(CLAUDE_MD, "hlds_linux", ENGINE_LIVE)
    assert f.ok and f.scope == "file"
    assert "WEAK check" in f.detail
    # ...and a weak check is still a check.
    assert not wl.check_row(CLAUDE_MD, "hlds_linux", "0" * 32).ok


def test_renamed_table_row_is_reported_not_assumed():
    """A mapped component with no row means the table moved under us. That is a
    finding, not a pass -- even when the md5 turns up somewhere in the file."""
    text = CLAUDE_MD.replace("| KTP-ReHLDS |", "| KTP ReHLDS Engine |")
    f = wl.check_row(text, "engine_i486.so", ENGINE_LIVE)
    assert f.scope == "no-row"
    assert "renamed" in f.detail


def test_every_mapped_component_name_is_a_plausible_row_name():
    for basename, component in wl.COMPONENT_BY_BASENAME.items():
        assert component and not component.startswith(" "), basename
        assert wl._norm(component), basename


# -- the ledger ------------------------------------------------------------

def test_record_rejects_a_non_md5():
    with pytest.raises(ValueError):
        wl.record_wave([{"basename": "x.amxx", "md5": "not-a-hash"}], hosts=["atlanta"], targets=24)


def test_record_round_trips():
    path = _stage(CVAR_LIVE, version="7.37")
    entry = json.loads(open(path, encoding="utf-8").read())
    assert entry["artifacts"][0]["md5"] == CVAR_LIVE
    assert entry["artifacts"][0]["version"] == "7.37"
    assert entry["reconciled_at"] is None
    assert len(wl.load_waves()) == 1


def test_uppercase_md5_is_stored_lowercase():
    path = _stage(CVAR_LIVE.upper())
    assert json.loads(open(path, encoding="utf-8").read())["artifacts"][0]["md5"] == CVAR_LIVE


# -- the gate --------------------------------------------------------------

def test_no_waves_is_clear(claude_md):
    assert wl.gate(claude_md).status == "clear"


def test_stale_row_blocks(claude_md):
    """2026-09-01, reproduced: one wave, two artifacts, neither row flipped.

    Both stale at once is the point -- this was a process defect, not two
    mistakes, so the gate has to name every row the wave moved."""
    _stage_multi([_artifact(CVAR_LIVE, version="7.37"),
                  _artifact(MH_LIVE, "KTPMatchHandler.amxx", "0.10.170")])
    res = wl.gate(claude_md)
    assert res.status == "blocked"
    _entry, bad = res.blocked[0]
    assert {f.basename for f in bad} == {"ktp_cvar.amxx", "KTPMatchHandler.amxx"}
    msg = "\n".join(wl.format_block(res, claude_md))
    assert "ACTIVATED" in msg and "still stale" in msg
    assert CVAR_LIVE in msg and MH_LIVE in msg


def test_one_stale_artifact_blocks_a_wave_whose_other_row_is_fine(claude_md):
    _stage_multi([_artifact(ENGINE_LIVE, "engine_i486.so"),
                  _artifact(MH_LIVE, "KTPMatchHandler.amxx", "0.10.170")])
    res = wl.gate(claude_md)
    assert res.status == "blocked"
    assert [f.basename for f in res.blocked[0][1]] == ["KTPMatchHandler.amxx"]


def test_two_waves_recorded_in_the_same_second_both_survive():
    """Second-resolution ids collide; an overwrite here would drop the very
    entry the gate exists to hold."""
    staged = dt.datetime.now(dt.timezone.utc).timestamp() - 2 * 86400
    a = wl.record_wave([_artifact(CVAR_LIVE)], hosts=["atlanta"], targets=24, staged_at=staged)
    b = wl.record_wave([_artifact(MH_LIVE, "KTPMatchHandler.amxx")],
                       hosts=["atlanta"], targets=24, staged_at=staged)
    assert a != b
    assert len(wl.load_waves()) == 2


def test_a_wave_that_has_not_activated_yet_does_not_block(claude_md):
    """Staged this evening, swaps at 03:00. There is nothing to flip yet, and
    blocking here would make the gate fire on every same-day restage."""
    _stage(MH_LIVE, basename="KTPMatchHandler.amxx", days_ago=0)
    res = wl.gate(claude_md)
    assert res.status == "clear"
    assert "not yet activated" in " ".join(res.lines)


def test_flipping_the_row_clears_the_gate(claude_md):
    """The whole design: no second command to remember. Editing CLAUDE.md is
    what unblocks the next stage."""
    _stage(MH_LIVE, basename="KTPMatchHandler.amxx", version="0.10.170")
    assert wl.gate(claude_md).status == "blocked"

    text = open(claude_md, encoding="utf-8").read().replace(
        "| KTPMatchHandler | **0.10.168** | 08-28 | `2cb28c15cccccccccccccccccccccccc` |",
        f"| KTPMatchHandler | **0.10.170** | 09-02 | `{MH_LIVE}` |")
    open(claude_md, "w", encoding="utf-8").write(text)

    assert wl.gate(claude_md).status == "clear"
    assert wl.load_waves() == []                       # reconciled, so it stops blocking
    assert len(wl.load_waves(include_reconciled=True)) == 1
    assert wl.load_waves(include_reconciled=True)[0][1]["reconciled_by"] == "stage-gate"


def test_unreadable_claude_md_is_inconclusive_never_a_pass(tmp_path):
    """The distinction that keeps this honest: 'I could not look' must not be
    reported as 'the row is fine'."""
    _stage(MH_LIVE, basename="KTPMatchHandler.amxx")
    res = wl.gate(str(tmp_path / "does-not-exist.md"))
    assert res.status == "inconclusive"
    assert "could not be read" in " ".join(res.lines)


def test_an_empty_claude_md_blocks_rather_than_reading_as_missing(tmp_path):
    """Control for the case above: a file that exists but says nothing is a
    STALE row, not an unreadable one. The two must not collapse."""
    p = tmp_path / "CLAUDE.md"
    p.write_text("", encoding="utf-8")
    _stage(MH_LIVE, basename="KTPMatchHandler.amxx")
    assert wl.gate(str(p)).status == "blocked"


def test_no_clear_reports_without_consuming_the_wave(claude_md):
    _stage(ENGINE_LIVE, basename="engine_i486.so")
    assert wl.gate(claude_md, auto_clear=False).status == "clear"
    assert len(wl.load_waves()) == 1                   # still pending
    assert wl.gate(claude_md).status == "clear"
    assert wl.load_waves() == []


# -- CLI surface -----------------------------------------------------------

def test_check_exit_codes(claude_md, capsys):
    assert wl.main(["--claude-md", claude_md, "check"]) == 0
    _stage(MH_LIVE, basename="KTPMatchHandler.amxx")
    assert wl.main(["--claude-md", claude_md, "check"]) == 1
    capsys.readouterr()


def test_check_is_inconclusive_with_code_2(tmp_path, capsys):
    _stage(MH_LIVE, basename="KTPMatchHandler.amxx")
    assert wl.main(["--claude-md", str(tmp_path / "nope.md"), "check"]) == 2
    capsys.readouterr()


def test_reconcile_without_the_fleet_says_so_and_still_gates(claude_md, capsys):
    _stage(MH_LIVE, basename="KTPMatchHandler.amxx")
    assert wl.main(["--claude-md", claude_md, "reconcile", "--no-fleet"]) == 1
    out = capsys.readouterr()
    assert "fleet NOT read" in out.out
    assert "STALE" in out.out


def test_reconcile_no_fleet_marks_its_own_weaker_provenance(claude_md, capsys):
    _stage(ENGINE_LIVE, basename="engine_i486.so")
    assert wl.main(["--claude-md", claude_md, "reconcile", "--no-fleet"]) == 0
    capsys.readouterr()
    entry = wl.load_waves(include_reconciled=True)[0][1]
    assert entry["reconciled_by"] == "reconcile --no-fleet"


def test_status_lists_pending_waves(claude_md, capsys):
    _stage(CVAR_LIVE, version="7.37")
    assert wl.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "ACTIVATED" in out and CVAR_LIVE in out and "7.37" in out
