"""Regression tests for scripts/fleet-audit-gate.sh.

The gate decides whether a weekly audit wakes a human (via the model that
writes for one). Its previous form lived inside fleet-audit.yml, untested, and
its restart-drift leg fired on the script's nonzero exit -- which is the normal
state whenever the tracked .example runs ahead of the fleet. Every run triaged;
every triage said "known, no action". These tests pin the replacement:
restart-drift is news when it CHANGES, not while it persists.

Nothing here touches a host. Each test lays the three collect outputs in
tmp_path and points KTP_GATE_STATE_DIR at a sibling directory.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

GATE = Path(__file__).parents[2] / "scripts" / "fleet-audit-gate.sh"
# CI runs plain bash; on a Windows workstation "bash" resolves to WSL's, which
# cannot see these paths -- point KTP_TEST_BASH at Git Bash there.
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")

CLEAN_STDOUT = "Snapshotting 5 hosts in parallel...\nRepo-drift delta vs last run: +0 new, -0 resolved\n"
CLEAN_REPORT = "dod-27015: parse=OK oldtype=disabled samesocket=armed duppid=armed\n"
CLEAN_DRIFT = "\nhosts reached: 5/5  clean: 5  drifted: 0\n"

# What the fleet actually reported on 2026-09-15: the .example ahead of every
# host. True, known, and not news on the second sighting.
KNOWN_DRIFT = (
    "Atlanta:\n  DRIFT: /home/dodserver/ktp-scheduled-restart.sh DIVERGES from scripts/ktp-scheduled-restart.sh.example (compared with secret values masked)\n"
    "Dallas:\n  DRIFT: /home/dodserver/ktp-scheduled-restart.sh DIVERGES from scripts/ktp-scheduled-restart.sh.example (compared with secret values masked)\n"
    "\nhosts reached: 5/5  clean: 3  drifted: 2\n"
)


CLEAN_DISTRIBUTE = (
    "# Distribute-tree drift\n\n"
    "No divergence: every watched path matches on every target.\n\n"
    "targets reached: 24/24  paths with drift: 0  per-instance hazards: 0\n"
)

# The shape the tree actually had on 2026-09-28: long-standing source-vs-fleet
# divergence, plus one file carrying per-instance data that nothing declares.
# Known on the second sighting -- except the hazard, which is a level by design.
STANDING_DISTRIBUTE = (
    "DRIFT: configs/ktpbasic.cfg shape=uniform targets=24 src=0123456789abcdef\n"
    "DRIFT: configs/servernamedefault.cfg shape=per-instance targets=24 src=fedcba9876543210\n"
    "targets reached: 24/24  paths with drift: 2  per-instance hazards: 1\n"
)


def _lay(work: Path, stdout=CLEAN_STDOUT, report=CLEAN_REPORT, drift=CLEAN_DRIFT,
         health=None, distribute=CLEAN_DISTRIBUTE) -> None:
    work.mkdir(parents=True, exist_ok=True)
    (work / "audit-stdout.txt").write_text(stdout, newline="\n")
    (work / "audit-report.md").write_text(report, newline="\n")
    (work / "restart-drift.txt").write_text(drift, newline="\n")
    dd = work / "distribute-drift.txt"
    if distribute is not None:
        dd.write_text(distribute, newline="\n")
    elif dd.exists():
        dd.unlink()
    hs = work / "health-state.json"
    if health is not None:
        hs.write_text(json.dumps(health), newline="\n")
    elif hs.exists():
        hs.unlink()


def _run(work: Path, state: Path) -> dict:
    state.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [BASH, GATE.as_posix()], cwd=work, capture_output=True, text=True, timeout=60,
        env=dict(os.environ, KTP_GATE_STATE_DIR=state.as_posix()),
    )
    assert r.returncode == 0, r.stderr
    out = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    assert set(out) == {"needs_triage", "reason"}, r.stdout
    return out


def test_clean_first_run_is_quiet_and_seeds_state(tmp_path):
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work)
    out = _run(work, state)
    assert out["needs_triage"] == "false"
    assert out["reason"] == "Nothing new."
    assert (state / "ktp-restart-drift-ci.txt").exists()


def test_persistent_known_drift_is_not_news(tmp_path):
    """The .example ahead of the fleet, two weeks running: quiet both times.
    First run has no baseline and must not triage everything at once; second
    run sees no change."""
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, drift=KNOWN_DRIFT)
    assert _run(work, state)["needs_triage"] == "false"
    _lay(work, drift=KNOWN_DRIFT)
    out = _run(work, state)
    assert out["needs_triage"] == "false", out


def test_new_divergence_is_news(tmp_path):
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, drift=KNOWN_DRIFT)
    _run(work, state)
    _lay(work, drift=KNOWN_DRIFT.replace("hosts reached: 5/5  clean: 3  drifted: 2",
                                         "hosts reached: 5/5  clean: 2  drifted: 3")
         .replace("Dallas:", "Denver:\n  DRIFT: /home/dodserver/status.sh is ABSENT\nDallas:"))
    out = _run(work, state)
    assert out["needs_triage"] == "true"
    assert "changed since last run" in out["reason"]


def test_resolution_is_also_news(tmp_path):
    """Drift going away is a change worth a line -- it is how a redeploy gets
    confirmed without anyone re-deriving it by hand."""
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, drift=KNOWN_DRIFT)
    _run(work, state)
    _lay(work, drift=CLEAN_DRIFT)
    assert _run(work, state)["needs_triage"] == "true"


def test_unreachable_detail_text_is_not_a_change(tmp_path):
    """Two identical outages carry different redacted exception text. Only the
    host and exception class count."""
    work, state = tmp_path / "w", tmp_path / "s"
    a = "Chicago: UNREACHABLE (TimeoutError) timed out after 15s to [redacted]\n\nhosts reached: 4/5  clean: 4  drifted: 0\n"
    b = "Chicago: UNREACHABLE (TimeoutError) connect attempt 2 failed [redacted]\n\nhosts reached: 4/5  clean: 4  drifted: 0\n"
    _lay(work, drift=a)
    _run(work, state)
    _lay(work, drift=b)
    assert _run(work, state)["needs_triage"] == "false"


def test_restart_drift_not_completing_is_always_news(tmp_path):
    """No 'hosts reached' summary means the instrument broke, not that the
    fleet drifted. That never goes quiet, baseline or not."""
    work, state = tmp_path / "w", tmp_path / "s"
    broken = "ERROR: paramiko not installed (pip3 install paramiko)\n"
    _lay(work, drift=broken)
    out = _run(work, state)
    assert out["needs_triage"] == "true"
    assert "did not complete" in out["reason"]
    _lay(work, drift=broken)
    assert _run(work, state)["needs_triage"] == "true"


def test_new_repo_drift_is_news(tmp_path):
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, stdout="Repo-drift delta vs last run: +5 new, -5 resolved\n")
    out = _run(work, state)
    assert out["needs_triage"] == "true"
    assert "5 new repo-drift" in out["reason"]


def test_monitor_fault_is_news_on_the_first_run(tmp_path):
    """No state involved: an armed old-type check kills live servers and must
    surface the first time it is seen."""
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, report="dod-27016: parse=OK oldtype=armed samesocket=armed duppid=armed\n")
    out = _run(work, state)
    assert out["needs_triage"] == "true"
    assert "monitor patch fault" in out["reason"]


def test_reasons_accumulate(tmp_path):
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, stdout="Repo-drift delta vs last run: +1 new, -0 resolved\n",
         report="dod-27015: parse=BROKEN oldtype=? samesocket=? duppid=?\n")
    out = _run(work, state)
    assert "1 new repo-drift" in out["reason"] and "monitor patch fault" in out["reason"]


# --- long-open health items, and a health check that stopped writing ---------

def _ts(delta: timedelta) -> str:
    return (datetime.now() - delta).strftime("%Y-%m-%d %H:%M:%S")


def _health(items: dict, updated_ago=timedelta(minutes=20)) -> dict:
    return {"updated_at": _ts(updated_ago), "down": list(items),
            "since": {k: _ts(v) for k, v in items.items()}, "detail": {}}


def test_a_fresh_health_item_is_the_channels_job_not_ours(tmp_path):
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, health=_health({"failed-unit:x.service": timedelta(hours=5)}))
    assert _run(work, state)["needs_triage"] == "false"


def test_an_item_open_for_days_fires_and_names_itself(tmp_path):
    """ktp-identity-reconcile sat failed ten days after its one Discord post.
    Age, not presence, is the signal."""
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, health=_health({"failed-unit:ktp-identity-reconcile.service": timedelta(days=10),
                               "disk-growth:/": timedelta(hours=2)}))
    out = _run(work, state)
    assert out["needs_triage"] == "true"
    assert "1 health item(s) open over 3d" in out["reason"]
    assert "ktp-identity-reconcile.service (10d)" in out["reason"]
    assert "disk-growth" not in out["reason"]


def test_it_nags_weekly_until_closed(tmp_path):
    """Unlike the restart-drift leg this one is a level, on purpose: the triage
    comments on the one open issue, and an item that is still open next week
    still has nobody on it."""
    work, state = tmp_path / "w", tmp_path / "s"
    for _ in range(2):
        _lay(work, health=_health({"failed-unit:x.service": timedelta(days=4)}))
        assert _run(work, state)["needs_triage"] == "true"


def test_a_health_check_that_stopped_writing_is_news(tmp_path):
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, health=_health({}, updated_ago=timedelta(hours=9)))
    out = _run(work, state)
    assert out["needs_triage"] == "true" and "has not written for 9h" in out["reason"]


def test_missing_or_pre_since_state_is_quiet(tmp_path):
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work)                                     # no health-state.json at all
    assert _run(work, state)["needs_triage"] == "false"
    _lay(work, health={"updated_at": _ts(timedelta(minutes=5)), "down": ["x"]})   # no since map
    assert _run(work, state)["needs_triage"] == "false"
    (work / "health-state.json").write_text("{}")   # the collect step's degrade value
    assert _run(work, state)["needs_triage"] == "false"


def test_threshold_is_tunable(tmp_path):
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, health=_health({"failed-unit:x.service": timedelta(days=2)}))
    assert _run(work, state)["needs_triage"] == "false"
    os.environ["KTP_GATE_LONG_OPEN_DAYS"] = "1"
    try:
        assert _run(work, state)["needs_triage"] == "true"
    finally:
        del os.environ["KTP_GATE_LONG_OPEN_DAYS"]


# --- the age is the FAULT's, not this estate's first sighting of it -----------
# `since` is stamped by the run that first saw an item, so a fault older than
# the producer watching it reads as new -- and under-counting is the direction
# that keeps a fault below this gate forever.

def _aged(items: dict, updated_ago=timedelta(minutes=20)) -> dict:
    """items: key -> (detected_ago, fault_ago | None)."""
    doc = {"updated_at": _ts(updated_ago), "down": list(items),
           "since": {k: _ts(v[0]) for k, v in items.items()}, "detail": {},
           "fault_since": {k: _ts(v[1]) for k, v in items.items() if v[1]}}
    return doc


def test_a_fault_older_than_its_watcher_is_aged_from_the_fault(tmp_path):
    """The measured case: stamped 2026-09-17 because `systemctl --failed` only
    became a producer on 09-16, for a unit that failed on 09-08. Four days
    against a three-day gate, for thirteen days of outage."""
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, health=_aged({"failed-unit:ktp-identity-reconcile.service":
                             (timedelta(days=4, hours=14), timedelta(days=13, hours=6))}))
    out = _run(work, state)
    assert out["needs_triage"] == "true"
    # Both numbers: the age decides, the detection date explains the silence.
    assert "ktp-identity-reconcile.service (13d, first seen 4d ago)" in out["reason"]


def test_a_fault_under_the_gate_by_detection_alone_still_fires(tmp_path):
    """The failure this change exists for. Detected yesterday, broken for two
    weeks: every threshold keyed on `since` stays quiet, indefinitely."""
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, health=_aged({"failed-unit:x.service":
                             (timedelta(hours=20), timedelta(days=14))}))
    out = _run(work, state)
    assert out["needs_triage"] == "true" and "(14d, first seen 0d ago)" in out["reason"]
    # ...and is silent without the onset, which is exactly the bug.
    _lay(work, health=_aged({"failed-unit:x.service": (timedelta(hours=20), None)}))
    assert _run(work, state)["needs_triage"] == "false"


def test_an_absent_onset_falls_back_rather_than_reading_as_age_zero(tmp_path):
    """Sparse by design: most item classes have no durable onset signal. An
    absent entry must mean "nothing knows", never "not a fault"."""
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, health=_aged({"failed-unit:x.service": (timedelta(days=9), None)}))
    out = _run(work, state)
    assert out["needs_triage"] == "true" and "x.service (9d)" in out["reason"]
    assert "first seen" not in out["reason"]


def test_a_junk_onset_does_not_take_the_item_out_of_the_reckoning(tmp_path):
    """An unparseable `fault_since` degrades to `since`; it must not swallow
    the item, which would turn a bad field into a silent gate."""
    work, state = tmp_path / "w", tmp_path / "s"
    doc = _aged({"failed-unit:x.service": (timedelta(days=9), None)})
    doc["fault_since"] = {"failed-unit:x.service": "not a timestamp"}
    _lay(work, health=doc)
    assert _run(work, state)["needs_triage"] == "true"


# --------------------------------------------------------- distribute-tree leg
def test_clean_distribute_tree_is_quiet(tmp_path):
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work)
    assert _run(work, state)["needs_triage"] == "false"


def test_standing_distribute_drift_is_not_news_twice_but_its_hazard_is(tmp_path):
    """The transition leg goes quiet on the second sighting; the per-instance
    hazard leg does not, and that asymmetry is the point of having both."""
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, distribute=STANDING_DISTRIBUTE)
    first = _run(work, state)
    second = _run(work, state)
    assert "changed since last run" not in second["reason"]
    assert "undeclared per-instance data" in first["reason"]
    assert "undeclared per-instance data" in second["reason"]
    assert second["needs_triage"] == "true"


def test_a_new_distribute_finding_is_news(tmp_path):
    work, state = tmp_path / "w", tmp_path / "s"
    hazardless = STANDING_DISTRIBUTE.replace(
        "DRIFT: configs/servernamedefault.cfg shape=per-instance targets=24 src=fedcba9876543210\n", ""
    ).replace("paths with drift: 2  per-instance hazards: 1",
              "paths with drift: 1  per-instance hazards: 0")
    _lay(work, distribute=hazardless)
    assert _run(work, state)["needs_triage"] == "false"      # baseline seeded, hazard-free
    _lay(work, distribute=hazardless + "DRIFT: addons/ktpamx/configs/ktp.ini shape=uniform targets=24 src=aaaabbbbccccdddd\n")
    out = _run(work, state)
    assert out["needs_triage"] == "true"
    assert "Distribute-tree drift changed since last run" in out["reason"]


def test_a_distribute_check_that_did_not_finish_is_always_news(tmp_path):
    """A sweep that died renders identically to a clean fleet. The completion
    marker is what tells them apart."""
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, distribute="Traceback (most recent call last):\nOSError\n")
    out = _run(work, state)
    assert out["needs_triage"] == "true"
    assert "Distribute-drift check did not complete" in out["reason"]


def test_a_missing_distribute_report_is_news_not_silence(tmp_path):
    work, state = tmp_path / "w", tmp_path / "s"
    _lay(work, distribute=None)
    assert "Distribute-drift check did not complete" in _run(work, state)["reason"]
