"""ktp-wave-ledger cancel: recording a wave that was unstaged before its swap.

The ledger had two resolved states, reconciled and nothing, so a wave whose
artifacts were deliberately removed before 03:00 stayed pending for ever. That
is not cosmetic: the row-flip gate sits on the *next* stage, so an uncancellable
wave blocks the stage that fixes it, and the only escape was
`--allow-unreconciled`, which lifts the gate for every wave rather than
resolving one.

Cancelling is a claim about the past, so the tests that matter are the refusals.
A row saying a wave never happened, over a fleet running its artifact, is worse
than the pending row it replaces -- so `cancel_check` must refuse on an
activated wave, on one still staged, on an unread fleet, and on the case nobody
expects: staged bytes equal to the live bytes, where absence is unobservable.

Nothing here touches the fleet, the network, or the real ledger directory.
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
        "ktp_wave_ledger_cancel", os.path.join(_ROOT, "scripts", "ktp-wave-ledger.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ktp_wave_ledger_cancel"] = mod
    spec.loader.exec_module(mod)
    return mod


wl = _load()

STAGED_MD5 = "1b14bcc4277e6d24f641402587a0d8e8"   # the artifact that was unstaged
LIVE_MD5 = "7aed80db3390c3d9b736dc22e0fc2161"     # what stayed live
BASENAME = "stats_logging.amxx"
INSTS = [f"atlanta:{p}" for p in range(27015, 27020)]


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("KTP_WAVE_LEDGER_DIR", str(tmp_path / "waves"))


def _stage(md5=STAGED_MD5, *, days_ago=0.1):
    staged = dt.datetime.now(dt.timezone.utc).timestamp() - days_ago * 86400
    return wl.record_wave(
        [{"basename": BASENAME, "md5": md5, "version": "1.37.0",
          "remote_dir": "serverfiles/dod/addons/ktpamx/plugins"}],
        hosts=["atlanta"], targets=5, staged_at=staged)


def _entry():
    # include_reconciled: the helper must still find a wave AFTER it is
    # resolved, or every refusal test loses its own subject.
    (_p, e), = wl.load_waves(include_reconciled=True)
    return e


def _read(*, live=LIVE_MD5, staged=None, errors=None):
    """A FleetRead as the real one comes back: every instance answering."""
    r = wl.FleetRead()
    r.live[BASENAME] = {i: live for i in INSTS}
    if staged:
        r.staged[BASENAME] = {i: staged for i in INSTS}
    if errors:
        r.errors.update(errors)
    return r


# -- the one case that should pass -----------------------------------------

def test_cancel_allowed_when_absent_and_unstaged():
    _stage()
    chk = wl.cancel_check(_entry(), _read())
    assert chk.ok, chk.lines
    # It must say what it verified, not merely succeed.
    assert any("no artifact of this wave is live" in ln for ln in chk.lines)
    assert any(str(len(INSTS)) in ln for ln in chk.lines)


# -- the refusals, which are the point -------------------------------------

def test_refuses_a_wave_live_on_its_whole_scope():
    """Uniform live == staged. The ledger records no replaced md5, so this does
    NOT prove activation -- a wave that staged bytes already live reads the
    same. The refusal must claim only what the fleet can support."""
    _stage()
    chk = wl.cancel_check(_entry(), _read(live=STAGED_MD5))
    assert not chk.ok
    assert any("cannot" in ln and "tell those apart" in ln for ln in chk.lines)
    assert any("reconcile it" in ln for ln in chk.lines)
    # It must NOT assert activation, which it cannot know.
    assert not any("this wave ACTIVATED" in ln for ln in chk.lines)


def test_refuses_a_partial_activation_and_names_it():
    """Mixed live: here activation IS observable, on part of the scope."""
    _stage()
    r = wl.FleetRead()
    r.live[BASENAME] = {i: LIVE_MD5 for i in INSTS}
    r.live[BASENAME][INSTS[0]] = STAGED_MD5
    r.live[BASENAME][INSTS[1]] = STAGED_MD5
    chk = wl.cancel_check(_entry(), r)
    assert not chk.ok
    assert any("ACTIVATED on part of its scope" in ln for ln in chk.lines)
    assert any("2/5" in ln for ln in chk.lines)
    assert any(INSTS[0] in ln for ln in chk.lines)


def test_refuses_a_wave_still_staged():
    _stage()
    chk = wl.cancel_check(_entry(), _read(staged=STAGED_MD5))
    assert not chk.ok
    assert any("STILL STAGED" in ln for ln in chk.lines)


def test_a_different_new_does_not_block_the_cancel():
    """Someone else's .new is not this wave's -- the md5 is the identity."""
    _stage()
    chk = wl.cancel_check(_entry(), _read(staged="deadbeef" * 4))
    assert chk.ok, chk.lines


def test_refuses_when_no_instance_reported_the_artifact():
    """An empty read is unestablished absence, not proven absence."""
    _stage()
    r = wl.FleetRead()
    r.live[BASENAME] = {}
    chk = wl.cancel_check(_entry(), r)
    assert not chk.ok
    assert any("unestablished" in ln for ln in chk.lines)


def test_refuses_a_no_op_wave_by_the_same_rule():
    """Same guard, reached the other way: a wave whose staged bytes were ALREADY
    live. Distinct scenario, identical evidence -- which is exactly why the
    refusal is worded as indistinguishability rather than as activation."""
    _stage(md5=LIVE_MD5)
    chk = wl.cancel_check(_entry(), _read(live=LIVE_MD5))
    assert not chk.ok
    assert any("tell those apart" in ln for ln in chk.lines)


def test_an_out_of_scope_host_is_not_evidence():
    """A live hit on a host this wave never targeted must not block it."""
    _stage()
    r = wl.FleetRead()
    r.live[BASENAME] = {i: LIVE_MD5 for i in INSTS}
    r.live[BASENAME]["denver:27015"] = STAGED_MD5     # not in hosts=["atlanta"]
    chk = wl.cancel_check(_entry(), r)
    assert chk.ok, chk.lines


# -- the marker, and the wiring that makes it count ------------------------

def test_mark_cancelled_writes_the_reason_and_resolves_the_wave():
    path = _stage()
    assert len(wl.load_waves()) == 1
    wl.mark_cancelled(path, _entry(), "native missing from the fielded module", "cancel")

    # Resolved: it must drop out of the unresolved list, which is what the
    # row-flip gate reads -- that is the whole reason this verb exists.
    assert wl.load_waves() == []
    assert len(wl.load_waves(include_reconciled=True)) == 1

    on_disk = json.loads(open(path, encoding="utf-8").read())
    assert on_disk["cancelled_reason"] == "native missing from the fielded module"
    assert isinstance(on_disk["cancelled_at"], int)
    assert on_disk["cancelled_by"] == "cancel"
    assert on_disk.get("cancelled_actor")
    # It did not pretend to ship.
    assert on_disk["reconciled_at"] is None


def test_the_gate_is_clear_after_a_cancel(tmp_path):
    """Wiring, not rules: an activated-but-cancelled wave must stop blocking."""
    path = _stage(days_ago=2.0)                      # long since activated
    cm = tmp_path / "CLAUDE.md"
    cm.write_text("# KTP\n\nno row for this artifact at all\n", encoding="utf-8")

    before = wl.gate(claude_md=str(cm))
    assert before.status == "blocked", before.lines

    wl.mark_cancelled(path, _entry(), "unstaged before the swap", "cancel")
    after = wl.gate(claude_md=str(cm))
    assert after.status == "clear", after.lines


def test_status_labels_a_cancelled_wave(capsys):
    path = _stage()
    wl.mark_cancelled(path, _entry(), "unstaged before the swap", "cancel")

    class A:
        all = True
    assert wl._cmd_status(A()) == 0
    out = capsys.readouterr().out
    assert "CANCELLED" in out
    assert "unstaged before the swap" in out


# -- the command's own refusals (no fleet is reached) ----------------------

def test_cmd_cancel_refuses_an_unknown_wave(capsys):
    class A:
        wave_id = "20990101T000000Z"
        reason = "x"
        claude_md = None
    assert wl._cmd_cancel(A()) == 2
    assert "No wave" in capsys.readouterr().err


def test_cmd_cancel_refuses_a_reconciled_wave(capsys):
    path = _stage()
    wl.mark_reconciled(path, _entry(), "stage-gate")

    class A:
        wave_id = _entry()["wave_id"]
        reason = "x"
        claude_md = None
    assert wl._cmd_cancel(A()) == 2
    assert "cannot be cancelled" in capsys.readouterr().err


def test_cmd_cancel_refuses_a_second_cancel(capsys):
    """A double cancel must not silently overwrite the first reason."""
    path = _stage()
    wl.mark_cancelled(path, _entry(), "the original reason", "cancel")

    class A:
        wave_id = _entry()["wave_id"]
        reason = "a different reason"
        claude_md = None
    assert wl._cmd_cancel(A()) == 2
    err = capsys.readouterr().err
    assert "already cancelled" in err
    assert "the original reason" in err
    assert json.loads(open(path, encoding="utf-8").read())["cancelled_reason"] == \
        "the original reason"


def test_cmd_cancel_refuses_an_unread_fleet(monkeypatch, capsys):
    """Fail closed: an unreachable fleet cannot establish that nothing shipped."""
    _stage()
    monkeypatch.setattr(wl, "fleet_read",
                        lambda *a, **k: _read(errors={"atlanta": "timed out"}))

    class A:
        wave_id = _entry()["wave_id"]
        reason = "x"
        claude_md = None
    assert wl._cmd_cancel(A()) == 2
    assert "refusal, not a warning" in capsys.readouterr().err
    # And it stayed unresolved.
    assert len(wl.load_waves()) == 1


def test_cmd_cancel_end_to_end_with_a_stubbed_fleet(monkeypatch, capsys):
    _stage()
    monkeypatch.setattr(wl, "fleet_read", lambda *a, **k: _read())

    class A:
        wave_id = _entry()["wave_id"]
        reason = "staged plugin called a native the fielded module lacks"
        claude_md = None
    assert wl._cmd_cancel(A()) == 0
    out = capsys.readouterr().out
    assert "CANCELLED" in out
    assert "No version row changes" in out
    assert wl.load_waves() == []


def test_cancel_reads_only_the_waves_own_hosts(monkeypatch):
    """It must not sweep the fleet: a cancel is about one wave's instances."""
    _stage()
    seen = {}

    def _spy(basenames, hosts=None):
        seen["hosts"] = hosts
        seen["basenames"] = basenames
        return _read()

    monkeypatch.setattr(wl, "fleet_read", _spy)

    class A:
        wave_id = _entry()["wave_id"]
        reason = "x"
        claude_md = None
    assert wl._cmd_cancel(A()) == 0
    assert seen["hosts"] == ["atlanta"]
    assert BASENAME in seen["basenames"]
