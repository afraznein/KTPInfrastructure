"""Guards for `scripts/ktp-tier2-stack-drift.py`'s comparison + age-tracking.

The runner's module stack goes out of sync every time a fleet ABI wave
activates — routine, expected, and only fixed by a manual re-sync. Before this
change the drift message was a flat md5/mtime diff with no sense of time, so
"the runner is six hours behind a wave that just landed" and "nobody has
re-synced the runner in nine days" printed identically. That trains people to
skim past the alert. These tests guard the two things that matter:

  * the comparison itself still classifies runner-behind vs missing vs error
    correctly (unchanged from before this patch), and
  * the age tracker reports elapsed time honestly — carrying an unchanged
    mismatch forward, resetting the clock the instant the mismatch's shape
    changes, and forgetting a mismatch once it resolves.

Loaded by path, with `paramiko` stubbed: the script imports paramiko at import
time but none of the functions under test touch it.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ktp-tier2-stack-drift.py"


def _load_module():
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec = importlib.util.spec_from_file_location("_ktp_tier2_stack_drift", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def drift():
    return _load_module()


# --------------------------------------------------------------- positive control

def test_module_exposes_the_functions_under_test(drift):
    """If the loader silently produced a stub, every assertion below passes
    vacuously. Fail here instead."""
    for name in ("parse_md5sum", "parse_mtime", "compute_drift",
                 "update_drift_ages", "format_age", "annotate_drift"):
        assert callable(getattr(drift, name, None)), f"{name} missing from module"


# ------------------------------------------------------------------- parsing

def test_parse_md5sum_matches_on_path_suffix(drift):
    raw = (
        "8b06d8a24eef8313034ec5283f63fbcb  /home/dodserver/dod-27015/serverfiles/engine_i486.so\n"
        "fca6648909887e6298e1b81e8679002f  /home/dodserver/dod-27015/serverfiles/dod/addons/ktpamx/modules/dodx_ktp_i386.so\n"
    )
    out = drift.parse_md5sum(raw, ["engine_i486.so", "dod/addons/ktpamx/modules/dodx_ktp_i386.so"])
    assert out["engine_i486.so"] == "8b06d8a24eef8313034ec5283f63fbcb"
    assert out["dod/addons/ktpamx/modules/dodx_ktp_i386.so"] == "fca6648909887e6298e1b81e8679002f"


def test_parse_mtime_ignores_non_numeric_lines(drift):
    raw = "1787000000 /home/dodserver/dod-27015/serverfiles/dod/addons/ktpamx/plugins/KTPMatchHandler.amxx\nnot a stat line\n"
    out = drift.parse_mtime(raw, ["dod/addons/ktpamx/plugins/KTPMatchHandler.amxx"])
    assert out["dod/addons/ktpamx/plugins/KTPMatchHandler.amxx"] == 1787000000


# ------------------------------------------------------------------- compute_drift

def _fake_fs(md5_map=None, mtime_map=None, present=None):
    """Build md5_fn/exists_fn/mtime_fn stand-ins over an in-memory {path: value} map."""
    md5_map = md5_map or {}
    mtime_map = mtime_map or {}
    present = present if present is not None else set(md5_map) | set(mtime_map)

    def exists_fn(path):
        return any(path.endswith(p) for p in present)

    def md5_fn(path):
        for p, v in md5_map.items():
            if path.endswith(p):
                return v
        raise AssertionError(f"no fake md5 for {path}")

    def mtime_fn(path):
        for p, v in mtime_map.items():
            if path.endswith(p):
                return v
        raise AssertionError(f"no fake mtime for {path}")

    return md5_fn, exists_fn, mtime_fn


def test_matching_stack_reports_no_drift(drift):
    md5_fn, exists_fn, mtime_fn = _fake_fs(md5_map={"engine_i486.so": "aaaa"})
    drifts, errors = drift.compute_drift(
        ["engine_i486.so"], [], {"engine_i486.so": "aaaa"}, {},
        "/opt/runner", 3 * 86400, "1.2.3.4",
        md5_fn=md5_fn, exists_fn=exists_fn, mtime_fn=mtime_fn,
    )
    assert drifts == []
    assert errors == []


def test_mismatched_stack_file_names_runner_then_fleet(drift):
    """Direction matters: a reader must be able to tell which side is which
    without cross-referencing anything else."""
    md5_fn, exists_fn, mtime_fn = _fake_fs(md5_map={"engine_i486.so": "eedfc99e97652b3e"})
    drifts, errors = drift.compute_drift(
        ["engine_i486.so"], [], {"engine_i486.so": "da27ce9eaa112233"}, {},
        "/opt/runner", 3 * 86400, "74.91.121.9",
        md5_fn=md5_fn, exists_fn=exists_fn, mtime_fn=mtime_fn,
    )
    assert not errors
    [(path, msg, sig)] = drifts
    assert path == "engine_i486.so"
    assert msg.index("runner eedfc99e") < msg.index("fleet da27ce9e")
    assert sig == "eedfc99e97652b3e:da27ce9eaa112233"


def test_missing_on_reference_host_is_an_error_not_a_drift(drift):
    """A path absent from the fleet reference means the check couldn't run,
    not that the runner disagrees with it — these must stay separate so a
    transient SSH/glob miss can't be read as drift."""
    md5_fn, exists_fn, mtime_fn = _fake_fs()
    drifts, errors = drift.compute_drift(
        ["engine_i486.so"], [], {}, {},
        "/opt/runner", 3 * 86400, "74.91.121.9",
        md5_fn=md5_fn, exists_fn=exists_fn, mtime_fn=mtime_fn,
    )
    assert drifts == []
    assert errors == ["engine_i486.so: missing on reference host 74.91.121.9"]


def test_missing_on_runner_is_drift(drift):
    md5_fn, exists_fn, mtime_fn = _fake_fs(present=set())
    drifts, errors = drift.compute_drift(
        ["engine_i486.so"], [], {"engine_i486.so": "aaaa"}, {},
        "/opt/runner", 3 * 86400, "74.91.121.9",
        md5_fn=md5_fn, exists_fn=exists_fn, mtime_fn=mtime_fn,
    )
    assert not errors
    assert drifts == [("engine_i486.so", "engine_i486.so: missing on runner", "missing")]


def test_testmode_plugin_within_grace_is_not_drift(drift):
    """A test-mode plugin whose fleet copy is newer by less than the grace
    window is a normal wave lag, not staleness."""
    md5_fn, exists_fn, mtime_fn = _fake_fs(mtime_map={"KTPMatchHandler.amxx": 1_000_000})
    drifts, errors = drift.compute_drift(
        [], ["KTPMatchHandler.amxx"], {}, {"KTPMatchHandler.amxx": 1_000_000 + 86400},
        "/opt/runner", 3 * 86400, "74.91.121.9",
        md5_fn=md5_fn, exists_fn=exists_fn, mtime_fn=mtime_fn,
    )
    assert drifts == []
    assert errors == []


def test_testmode_plugin_beyond_grace_is_drift_with_day_count(drift):
    md5_fn, exists_fn, mtime_fn = _fake_fs(mtime_map={"KTPPracticeMode.amxx": 1_000_000})
    fleet_mtime = 1_000_000 + 15 * 86400
    drifts, errors = drift.compute_drift(
        [], ["KTPPracticeMode.amxx"], {}, {"KTPPracticeMode.amxx": fleet_mtime},
        "/opt/runner", 3 * 86400, "74.91.121.9",
        md5_fn=md5_fn, exists_fn=exists_fn, mtime_fn=mtime_fn,
    )
    assert not errors
    [(path, msg, sig)] = drifts
    assert path == "KTPPracticeMode.amxx"
    assert "15d older" in msg
    assert sig == f"1000000:{fleet_mtime}"


# ------------------------------------------------------------------- age tracking

def test_new_drift_starts_at_zero_age(drift):
    items = [("engine_i486.so", "engine_i486.so: mismatch", "aaa:bbb")]
    state = drift.update_drift_ages({}, items, now=10_000)
    assert state == {"engine_i486.so": {"sig": "aaa:bbb", "since": 10_000}}
    [msg] = drift.annotate_drift(items, state, now=10_000)
    assert "just started" in msg


def test_unchanged_drift_carries_its_original_since_forward(drift):
    """The whole point of the state file: an old drift keeps aging instead of
    resetting to zero on every run."""
    prev = {"engine_i486.so": {"sig": "aaa:bbb", "since": 10_000}}
    items = [("engine_i486.so", "engine_i486.so: mismatch", "aaa:bbb")]
    now = 10_000 + 9 * 86400
    state = drift.update_drift_ages(prev, items, now=now)
    assert state["engine_i486.so"]["since"] == 10_000
    [msg] = drift.annotate_drift(items, state, now=now)
    assert "drifting 9d" in msg


def test_a_changed_mismatch_resets_the_clock(drift):
    """A runner that re-syncs to a DIFFERENT still-wrong value is a new event,
    not nine more days on the old one — otherwise a partial fix reads as an
    ancient, ignored problem."""
    prev = {"engine_i486.so": {"sig": "aaa:bbb", "since": 10_000}}
    items = [("engine_i486.so", "engine_i486.so: mismatch", "ccc:bbb")]
    now = 10_000 + 9 * 86400
    state = drift.update_drift_ages(prev, items, now=now)
    assert state["engine_i486.so"] == {"sig": "ccc:bbb", "since": now}
    [msg] = drift.annotate_drift(items, state, now=now)
    assert "just started" in msg


def test_resolved_drift_is_dropped_from_state(drift):
    """A path that stops drifting must not linger in state — if it drifts
    again later it should read as new, not as a revival of the old age."""
    prev = {
        "engine_i486.so": {"sig": "aaa:bbb", "since": 10_000},
        "reapi_ktp_i386.so": {"sig": "ccc:ddd", "since": 10_000},
    }
    # only engine_i486.so is still drifting this run
    items = [("engine_i486.so", "engine_i486.so: mismatch", "aaa:bbb")]
    state = drift.update_drift_ages(prev, items, now=20_000)
    assert "reapi_ktp_i386.so" not in state
    assert state["engine_i486.so"]["since"] == 10_000


@pytest.mark.parametrize(
    "age_seconds, expect_substring",
    [
        (60, "just started"),
        (299, "just started"),
        (300, "drifting 5m"),
        (3599, "drifting 59m"),
        (3600, "drifting 1h"),
        (86399, "drifting 23h"),
        (86400, "drifting 1d"),
        (9 * 86400, "drifting 9d"),
    ],
)
def test_format_age_buckets(drift, age_seconds, expect_substring):
    assert drift.format_age(age_seconds) == expect_substring
