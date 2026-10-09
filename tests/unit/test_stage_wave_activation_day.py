"""stage-wave.py refuses a wave whose 03:00 ET swap lands on a Saturday or Sunday.

The rule is judged by activation day: Saturday evening activates Sunday morning
(forbidden), Sunday evening activates Monday morning (fine). The clock is passed
in, so nothing here depends on when the suite runs.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_ROOT, "scripts")
ET = ZoneInfo("America/New_York")


def _load(mod_name, filename):
    spec = importlib.util.spec_from_file_location(mod_name, os.path.join(_SCRIPTS, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


if "paramiko" not in sys.modules:
    stub = types.ModuleType("paramiko")
    stub.SSHClient = object
    stub.AutoAddPolicy = object
    sys.modules["paramiko"] = stub

wl = _load("ktp_wave_ledger", "ktp-wave-ledger.py")
sw = _load("stage_wave", "stage-wave.py")


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET).timestamp()


# 2026-10-10 is a Saturday.
def test_saturday_evening_stage_activates_sunday_and_is_flagged():
    assert sw.weekend_activation(at(2026, 10, 10, 21)) == "Sunday"


def test_sunday_evening_stage_activates_monday_and_is_not_flagged():
    assert sw.weekend_activation(at(2026, 10, 11, 21)) is None


def test_friday_evening_stage_activates_saturday_and_is_flagged():
    assert sw.weekend_activation(at(2026, 10, 9, 21)) == "Saturday"


def test_early_saturday_before_the_swap_activates_the_same_morning():
    assert sw.weekend_activation(at(2026, 10, 10, 1)) == "Saturday"


def test_thursday_evening_is_fine():
    assert sw.weekend_activation(at(2026, 10, 8, 21)) is None


def test_ledger_stores_the_emergency_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("KTP_WAVE_LEDGER_DIR", str(tmp_path / "waves"))
    art = [{"basename": "x.amxx", "md5": "bf07ff9bf61e11edbc4d64b78abc0bff", "remote_dir": "p"}]
    path = wl.record_wave(art, ["denver"], 1, emergency="crash loop")
    assert '"emergency": "crash loop"' in open(path).read()
    path = wl.record_wave(art, ["denver"], 1, staged_at=1.0 + 86400 * 400)
    assert '"emergency": null' in open(path).read()


def _run_main(monkeypatch, capsys, now, extra=()):
    monkeypatch.setattr(sw.time, "time", lambda: now)
    monkeypatch.setattr(sw.freshness, "require_current", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["stage-wave.py", "--hosts", "denver", "--dry-run",
                                      "--allow-unreconciled", "--allow-existing-new", *extra])
    with pytest.raises(SystemExit) as ei:
        sw.main()
    return ei.value.code, capsys.readouterr()


def test_main_refuses_saturday_evening_without_emergency(monkeypatch, capsys):
    code, out = _run_main(monkeypatch, capsys, at(2026, 10, 10, 21))
    assert "league match day" in str(code)


def test_main_passes_the_gate_on_sunday_evening(monkeypatch, capsys):
    code, out = _run_main(monkeypatch, capsys, at(2026, 10, 11, 21))
    assert "league match day" not in str(code)


def test_main_accepts_emergency_with_a_reason(monkeypatch, capsys):
    code, out = _run_main(monkeypatch, capsys, at(2026, 10, 10, 21), ["--emergency", "crash loop"])
    assert "league match day" not in str(code)
    assert "crash loop" in out.out


def test_main_rejects_a_blank_emergency_reason(monkeypatch, capsys):
    code, _ = _run_main(monkeypatch, capsys, at(2026, 10, 10, 21), ["--emergency", " "])
    assert "needs a reason" in str(code)
