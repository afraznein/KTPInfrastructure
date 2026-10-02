"""Guards for `scripts/ktp-tier2-stack-drift.py`'s comparison + age-tracking.

The runner's module stack goes out of sync every time a fleet ABI wave
activates — routine, expected, and only fixed by a manual re-sync. Before this
change the drift message was a flat md5/mtime diff with no sense of time, so
"the runner is six hours behind a wave that just landed" and "nobody has
re-synced the runner in nine days" printed identically. That trains people to
skim past the alert. These tests guard the two things that matter:

  * the comparison itself still classifies runner-behind vs missing vs error
    correctly, and
  * the age tracker reports elapsed time honestly — carrying an unchanged
    mismatch forward, resetting the clock the instant the mismatch's shape
    changes, and forgetting a mismatch once it resolves.

The test-mode plugins used to be compared by mtime, and these tests now pin why
they are not. On 2026-09-28 the fleet's KTPPracticeMode had been re-copied by a
routine redistribute — mtime 17 days newer, source byte-identical, 1.4.9 on the
runner, on the fleet and on origin/main — and this checker had been reporting
"restage it" every six hours for days. `test_same_version_is_not_drift_however
_old_the_runner_copy_is` is that case, and it must keep failing if anyone
reintroduces a time-based trigger.

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
    for name in ("parse_md5sum", "compute_drift", "compute_config_drift",
                 "parse_version", "version_is_behind", "is_config_backup",
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


# ------------------------------------------------------------------- compute_drift

def _fake_fs(md5_map=None, version_map=None, present=None):
    """md5_fn/exists_fn/version_fn stand-ins over in-memory {path: value} maps."""
    md5_map = md5_map or {}
    version_map = version_map or {}
    present = present if present is not None else set(md5_map) | set(version_map)

    def exists_fn(path):
        return any(path.endswith(p) for p in present)

    def md5_fn(path):
        for p, v in md5_map.items():
            if path.endswith(p):
                return v
        raise AssertionError(f"no fake md5 for {path}")

    def version_fn(path):
        for p, v in version_map.items():
            if path.endswith(p):
                return v
        return None

    return md5_fn, exists_fn, version_fn


def test_matching_stack_reports_no_drift(drift):
    md5_fn, exists_fn, version_fn = _fake_fs(md5_map={"engine_i486.so": "aaaa"})
    drifts, errors = drift.compute_drift(
        ["engine_i486.so"], [], {"engine_i486.so": "aaaa"}, {},
        "/opt/runner", "reference-host",
        md5_fn=md5_fn, exists_fn=exists_fn, version_fn=version_fn,
    )
    assert drifts == []
    assert errors == []


def test_mismatched_stack_file_names_runner_then_fleet(drift):
    """Direction matters: a reader must be able to tell which side is which
    without cross-referencing anything else."""
    md5_fn, exists_fn, version_fn = _fake_fs(md5_map={"engine_i486.so": "eedfc99e97652b3e"})
    drifts, errors = drift.compute_drift(
        ["engine_i486.so"], [], {"engine_i486.so": "da27ce9eaa112233"}, {},
        "/opt/runner", "reference-host",
        md5_fn=md5_fn, exists_fn=exists_fn, version_fn=version_fn,
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
    md5_fn, exists_fn, version_fn = _fake_fs()
    drifts, errors = drift.compute_drift(
        ["engine_i486.so"], [], {}, {},
        "/opt/runner", "reference-host",
        md5_fn=md5_fn, exists_fn=exists_fn, version_fn=version_fn,
    )
    assert drifts == []
    assert errors == ["engine_i486.so: missing on reference host reference-host"]


def test_missing_on_runner_is_drift(drift):
    md5_fn, exists_fn, version_fn = _fake_fs(present=set())
    drifts, errors = drift.compute_drift(
        ["engine_i486.so"], [], {"engine_i486.so": "aaaa"}, {},
        "/opt/runner", "reference-host",
        md5_fn=md5_fn, exists_fn=exists_fn, version_fn=version_fn,
    )
    assert not errors
    assert drifts == [("engine_i486.so", "engine_i486.so: missing on runner", "missing")]


# ----------------------------------------- test-mode plugins: version, not elapsed time

def _testmode(drift, runner_v, fleet_v, path="KTPPracticeMode.amxx"):
    md5_fn, exists_fn, version_fn = _fake_fs(version_map={path: runner_v})
    return drift.compute_drift(
        [], [path], {}, {path: fleet_v},
        "/opt/runner", "reference-host",
        md5_fn=md5_fn, exists_fn=exists_fn, version_fn=version_fn,
    )


def test_same_version_is_not_drift_however_old_the_runner_copy_is(drift):
    """The measured false positive, 2026-09-28. The fleet's copy had been
    re-copied by a routine redistribute -- 17 days of mtime, not one line of
    source -- and the old time-based check reported "restage it" every six
    hours for days while runner, fleet and origin/main all held 1.4.9. Nothing
    about elapsed time may reach this verdict."""
    drifts, errors = _testmode(drift, "1.4.9", "1.4.9")
    assert drifts == []
    assert errors == []


def test_runner_behind_the_fleet_is_drift(drift):
    """The shape of the 2026-08-03 incident: a green suite certifying plugin
    behaviour production does not have."""
    drifts, errors = _testmode(drift, "0.10.147", "0.10.149", path="KTPMatchHandler.amxx")
    assert not errors
    [(path, msg, sig)] = drifts
    assert path == "KTPMatchHandler.amxx"
    assert "runner holds 0.10.147" in msg and "fleet runs 0.10.149" in msg
    assert sig == "0.10.147:0.10.149"


def test_runner_ahead_of_the_fleet_is_not_drift(drift):
    """A pre-activation gate is SUPPOSED to lead, and KTPHudObserver is rebuilt
    from upstream master every run so it leads routinely. Flagging that trains
    people to dismiss the alert."""
    drifts, errors = _testmode(drift, "2.9.3", "2.9.1", path="KTPHudObserver.amxx")
    assert drifts == []
    assert errors == []


def test_unreadable_version_is_inconclusive_never_green(drift):
    """A decode that produced nothing is not evidence the runner is fine. It
    must land in errors (exit 2, "couldn't check"), not in a silent pass --
    that silence is the whole gap this check exists to close."""
    drifts, errors = _testmode(drift, None, "1.4.9")
    assert drifts == []
    assert len(errors) == 1 and "cannot order versions" in errors[0]


def test_testmode_plugin_missing_on_runner_is_drift(drift):
    md5_fn, exists_fn, version_fn = _fake_fs(present=set())
    drifts, errors = drift.compute_drift(
        [], ["KTPMatchHandler.amxx"], {}, {"KTPMatchHandler.amxx": "0.10.173"},
        "/opt/runner", "reference-host",
        md5_fn=md5_fn, exists_fn=exists_fn, version_fn=version_fn,
    )
    assert not errors
    assert drifts == [("KTPMatchHandler.amxx",
                       "KTPMatchHandler.amxx: missing on runner", "missing")]


@pytest.mark.parametrize(
    "runner, fleet, expected",
    [
        ("0.10.9", "0.10.10", True),    # not a string compare: "9" > "1" lexically
        ("0.10.10", "0.10.9", False),
        ("1.4", "1.4.0", False),        # unequal component counts are level
        ("1.4.0", "1.4", False),
        ("2.9.3", "2.10.0", True),
        (None, "1.0.0", None),
        ("1.0.0", None, None),
        ("dev", "1.0.0", None),
    ],
)
def test_version_ordering(drift, runner, fleet, expected):
    assert drift.version_is_behind(runner, fleet) is expected


# ------------------------------------------------------------------- configs

def test_config_matching_the_fleet_is_not_drift(drift):
    md5_fn, exists_fn, _ = _fake_fs(md5_map={"ktp_maps.ini": "aaaa"})
    drifts, errors = drift.compute_config_drift(
        {"ktp_maps.ini": "aaaa"}, "/opt/runner", "configs", {},
        md5_fn=md5_fn, exists_fn=exists_fn,
    )
    assert drifts == [] and errors == []


def test_config_differing_from_the_fleet_is_drift(drift):
    """ktp_maps.ini feeds match-handler map handling and sat 60 days behind the
    fleet with nothing watching it."""
    md5_fn, exists_fn, _ = _fake_fs(md5_map={"ktp_maps.ini": "1111aaaabbbbcccc"})
    drifts, errors = drift.compute_config_drift(
        {"ktp_maps.ini": "2222ddddeeeeffff"}, "/opt/runner", "configs", {},
        md5_fn=md5_fn, exists_fn=exists_fn,
    )
    assert not errors
    [(path, msg, sig)] = drifts
    assert path == "configs/ktp_maps.ini"
    assert msg.index("runner 1111aaaa") < msg.index("fleet 2222dddd")
    assert sig == "1111aaaabbbbcccc:2222ddddeeeeffff"


def test_config_present_on_the_fleet_and_absent_on_the_runner_is_drift(drift):
    """Unlike a binary, a config the harness simply does not have changes what
    the suite exercises -- dodx.ini was never copied across at all."""
    md5_fn, exists_fn, _ = _fake_fs(present=set())
    drifts, errors = drift.compute_config_drift(
        {"dodx.ini": "aaaa"}, "/opt/runner", "configs", {},
        md5_fn=md5_fn, exists_fn=exists_fn,
    )
    assert not errors
    assert drifts == [("configs/dodx.ini",
                       "configs/dodx.ini: on the fleet, absent on the runner", "missing")]


def test_runner_local_config_absent_on_the_runner_is_not_drift(drift):
    """hud_observer.cfg is absent ON PURPOSE -- it carries the live HUD ingest
    URL and key, and restoring it points the harness at the real ingest. An
    automated sweep has already tried to "fix" it once; this is the guard that
    keeps the next one from firing."""
    md5_fn, exists_fn, _ = _fake_fs(present=set())
    drifts, errors = drift.compute_config_drift(
        {"hud_observer.cfg": "aaaa"}, "/opt/runner", "configs",
        {"hud_observer.cfg": "absent on purpose"},
        md5_fn=md5_fn, exists_fn=exists_fn,
    )
    assert drifts == [] and errors == []


def test_hud_observer_cfg_is_actually_in_the_shipped_allowlist(drift):
    """The test above proves the MECHANISM. This proves the shipped list uses
    it -- a guard exercised only against a fixture protects nothing."""
    assert "hud_observer.cfg" in drift.CONFIGS_RUNNER_LOCAL


def test_every_runner_local_config_carries_a_reason(drift):
    """An unexplained exemption is how a real staleness gets parked here."""
    for name, reason in drift.CONFIGS_RUNNER_LOCAL.items():
        assert isinstance(reason, str) and reason.strip(), f"{name} has no reason"


@pytest.mark.parametrize(
    "name, ignored",
    [
        ("ktp_maps.ini", False),
        ("amxx.cfg", False),
        ("hud_observer.cfg", False),                   # a real name, not a backup
        ("plugins.ini.bak-20260421-202333", True),
        ("ktp_maps.ini.pre069", True),
        ("hud_observer.cfg.prod-stale-bak", True),
        ("users.ini.bak-preresync-20260714", True),
        ("KTPMatchHandler.amxx.0.10.112.backup", True),
    ],
)
def test_backup_filter(drift, name, ignored):
    """The estate puts the marker at the END of the name, so an extension-based
    filter would let every one of these through."""
    assert drift.is_config_backup(name) is ignored


def test_testmode_plugins_and_strict_plugins_do_not_overlap(drift):
    """A plugin in both lists would be md5-compared against a fleet build it is
    SUPPOSED to differ from -- a permanent false alarm. sync-runner-stack.py
    makes the same assertion before it writes; this catches it at test time."""
    assert not set(drift.PLUGINS_STRICT) & set(drift.PLUGINS_TESTMODE)


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


def test_every_plugin_the_fleet_loads_is_compared(drift):
    """A fleet plugin in neither list is never compared, so the runner can hold
    any build of it and stay green. stats_logging.amxx sat stale on the runner
    that way. The online plugins.ini is the shipped prod load list."""
    from tests.config_parse.parsers import parse_plugins_ini

    fleet = {e.filename for e in parse_plugins_ini(REPO / "config" / "online" / "plugins.ini")}
    assert "stats_logging.amxx" in fleet, "positive control: the parser read the load list"
    covered = {Path(p).name for p in drift.PLUGINS_STRICT + drift.PLUGINS_TESTMODE}
    assert sorted(fleet - covered) == []
