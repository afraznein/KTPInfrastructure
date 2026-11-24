"""ktp-wave-ledger: reconcile the RESTART, not the stage call.

The 03:00 swap activates every staged `.new`, whoever staged it. Two real
failures shaped these cases: a swap that activated two artifacts while the
ledger held one, and a stage that never entered the ledger at all. Nothing here
touches the network -- the fleet read is replaced with an in-memory FleetRead.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import sys
import types

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

ENGINE = "2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c"
CORE = "39393939393939393939393939393939"
STATS_OLD = "99999999999999999999999999999999"
STATS_NEW = "d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3d3"
CVAR_737 = "35353535353535353535353535353535"
CVAR_738 = "91919191919191919191919191919191"

# Shaped like today's table: KTPAMXX split into one row per artifact, a
# backticked first cell, and rollback pins after the live md5.
CLAUDE_MD = f"""\
| Component | Live | Since | Verified hash |
|---|---|---|---|
| KTP-ReHLDS | 3.22.0.990-dev | 09-04 | **`{ENGINE}`** |
| KTPAMXX core | **2.7.33** | 08-31 | **`{CORE}`** |
| `stats_logging.amxx` | **1.19.4** | 09-11 | **`{STATS_NEW}`** -- rollback `{STATS_OLD}` |
| KTPCvarChecker | **7.37** | 09-08 | **`{CVAR_737}`** |
"""

INSTS = ["atlanta:27015", "dallas:27015", "chicago:27018"]
PLUGINS = "serverfiles/dod/addons/ktpamx/plugins"


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("KTP_WAVE_LEDGER_DIR", str(tmp_path / "waves"))
    # The repo's real audit baseline would judge these fake md5s; it has its own tests.
    (tmp_path / "expected-binaries.conf").write_text("", encoding="utf-8")
    monkeypatch.setenv("KTP_EXPECTED_BINARIES", str(tmp_path / "expected-binaries.conf"))


@pytest.fixture
def claude_md(tmp_path):
    p = tmp_path / "CLAUDE.md"
    p.write_text(CLAUDE_MD, encoding="utf-8")
    return str(p)


def _read(live, staged=None, errors=None):
    # Duck-typed, so the same fixture drives the pre-change reconcile and shows it passing these fleets.
    r = types.SimpleNamespace(live={}, staged={}, errors={})
    for base, md5 in live.items():
        r.live[base] = dict(md5) if isinstance(md5, dict) else {i: md5 for i in INSTS}
    for base, md5 in (staged or {}).items():
        r.staged[base] = {i: md5 for i in INSTS}
    r.errors.update(errors or {})
    return r


def _fleet(read, monkeypatch):
    """Serve `read` to the new whole-fleet reader AND to the per-wave reader it replaced."""
    monkeypatch.setattr(wl, "fleet_read", lambda basenames, hosts=None: read, raising=False)
    monkeypatch.setattr(wl, "fleet_md5s",
                        lambda entry: {a["basename"]: read.live.get(a["basename"], {})
                                       for a in entry["artifacts"]},
                        raising=False)


def _stage(*artifacts, days_ago=2.0):
    staged = dt.datetime.now(dt.timezone.utc).timestamp() - days_ago * 86400
    return wl.record_wave([{"basename": b, "md5": m, "remote_dir": PLUGINS} for b, m in artifacts],
                          hosts=["atlanta", "dallas", "chicago"], targets=24, staged_at=staged)


def _run(argv):
    try:
        return wl.main(argv)
    except SystemExit as ex:
        return ex.code


CONSISTENT = {"engine_i486.so": ENGINE, "ktpamx_i386.so": CORE,
              "stats_logging.amxx": STATS_NEW, "ktp_cvar.amxx": CVAR_737}


# -- the two proven failures -----------------------------------------------

def test_a_restart_that_activated_two_artifacts_with_a_ledger_of_one_is_not_reconciled(
        claude_md, monkeypatch, capsys):
    """The ledger held stats_logging; the swap also activated ktp_cvar 7.38, whose row was never flipped."""
    _stage(("stats_logging.amxx", STATS_NEW))
    _fleet(_read({**CONSISTENT, "ktp_cvar.amxx": CVAR_738}), monkeypatch)

    rc = _run(["--claude-md", claude_md, "reconcile"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "UNLEDGERED_LIVE: ktp_cvar.amxx" in out
    assert len(wl.load_waves()) == 1, "the stats_logging wave must stay open while the restart disagrees"


def test_reconcile_with_no_wave_still_catches_a_stage_that_skipped_the_ledger(
        claude_md, monkeypatch, capsys):
    """No wave recorded it, so there was nothing to reconcile -- and the fleet had still moved."""
    os.makedirs(wl.ledger_dir())
    _fleet(_read({**CONSISTENT, "ktp_cvar.amxx": CVAR_738}), monkeypatch)

    assert _run(["--claude-md", claude_md, "reconcile"]) == 1
    assert "UNLEDGERED_LIVE: ktp_cvar.amxx" in capsys.readouterr().out


def test_sweep_flags_an_artifact_live_with_no_ledger_entry(claude_md, monkeypatch, capsys):
    os.makedirs(wl.ledger_dir())
    _fleet(_read({**CONSISTENT, "ktp_cvar.amxx": CVAR_738}), monkeypatch)

    assert _run(["--claude-md", claude_md, "sweep"]) == 1
    out = capsys.readouterr().out
    assert "UNLEDGERED_LIVE: ktp_cvar.amxx" in out and CVAR_738 in out


# -- consistent state ------------------------------------------------------

def test_a_consistent_restart_sweeps_clean(claude_md, monkeypatch, capsys):
    _stage(("stats_logging.amxx", STATS_NEW))
    _fleet(_read(CONSISTENT), monkeypatch)

    assert _run(["--claude-md", claude_md, "sweep"]) == 0
    assert "clean" in capsys.readouterr().out
    assert len(wl.load_waves()) == 1, "sweep is read-only; it never marks a wave"


def test_a_consistent_restart_reconciles_its_wave(claude_md, monkeypatch, capsys):
    """Control: the fixtures are not rigged to fail. Passes before and after the change."""
    _stage(("stats_logging.amxx", STATS_NEW))
    _fleet(_read(CONSISTENT), monkeypatch)

    assert _run(["--claude-md", claude_md, "reconcile"]) == 0
    capsys.readouterr()
    assert wl.load_waves() == []
    assert wl.load_waves(include_reconciled=True)[0][1]["reconciled_by"] == "reconcile"


def test_a_recorded_wave_whose_row_was_not_flipped_is_on_row_not_unledgered(claude_md, monkeypatch):
    _stage(("ktp_cvar.amxx", CVAR_738))
    found = wl.sweep(_read({**CONSISTENT, "ktp_cvar.amxx": CVAR_738}), CLAUDE_MD,
                     wl.load_waves(include_reconciled=True))
    kinds = {(f.kind, f.basename) for f in found}
    assert ("LIVE_NOT_ON_ROW", "ktp_cvar.amxx") in kinds
    assert ("ROW_NOT_LIVE", "ktp_cvar.amxx") in kinds


# -- the other shapes a restart can take -----------------------------------

def test_a_staged_new_outside_any_pending_wave_is_flagged_before_it_activates():
    read = _read(CONSISTENT, staged={"ktp_cvar.amxx": CVAR_738})
    found = wl.sweep(read, CLAUDE_MD, [])
    assert [(f.kind, f.basename, f.md5) for f in found] == [("STAGED_UNLEDGERED", "ktp_cvar.amxx", CVAR_738)]

    _stage(("ktp_cvar.amxx", CVAR_738), days_ago=0)
    assert wl.sweep(read, CLAUDE_MD, wl.load_waves(include_reconciled=True)) == []


def test_a_staged_unledgered_new_fails_reconcile_but_does_not_hold_the_activated_wave(
        claude_md, monkeypatch, capsys):
    _stage(("stats_logging.amxx", STATS_NEW))
    _fleet(_read(CONSISTENT, staged={"ktp_cvar.amxx": CVAR_738}), monkeypatch)

    assert _run(["--claude-md", claude_md, "reconcile"]) == 1
    assert "STAGED_UNLEDGERED" in capsys.readouterr().out
    assert wl.load_waves() == []


def test_a_partial_activation_is_not_uniform():
    split = {INSTS[0]: CVAR_738, INSTS[1]: CVAR_737, INSTS[2]: CVAR_737}
    found = wl.sweep(_read({**CONSISTENT, "ktp_cvar.amxx": split}), CLAUDE_MD, [])
    assert "NOT_UNIFORM" in {f.kind for f in found}


def test_a_row_that_names_the_new_build_while_the_fleet_runs_the_rollback():
    """The old md5 is on the row as a rollback pin, so the row check alone passes it."""
    assert wl.check_row(CLAUDE_MD, "stats_logging.amxx", STATS_OLD).ok
    found = wl.sweep(_read({**CONSISTENT, "stats_logging.amxx": STATS_OLD}), CLAUDE_MD, [])
    assert [(f.kind, f.md5) for f in found] == [("ROW_NOT_LIVE", STATS_NEW)]


def test_ktpamxx_artifacts_are_checked_against_their_own_rows():
    for base, md5 in (("ktpamx_i386.so", CORE), ("stats_logging.amxx", STATS_NEW)):
        f = wl.check_row(CLAUDE_MD, base, md5)
        assert f.ok and f.scope == "row", f.detail
    assert wl.row_claim(CLAUDE_MD, "stats_logging.amxx") == STATS_NEW


# -- never a pass by default -----------------------------------------------

def test_an_unreadable_instance_is_inconclusive(claude_md, monkeypatch, capsys):
    os.makedirs(wl.ledger_dir())
    _fleet(_read(CONSISTENT, errors={"denver": "timed out"}), monkeypatch)
    assert _run(["--claude-md", claude_md, "sweep"]) == 2
    assert _run(["--claude-md", claude_md, "reconcile"]) == 2
    capsys.readouterr()


def test_sweep_without_a_ledger_is_inconclusive_unless_told(claude_md, monkeypatch, capsys):
    _fleet(_read({**CONSISTENT, "ktp_cvar.amxx": CVAR_738}), monkeypatch)
    assert _run(["--claude-md", claude_md, "sweep"]) == 2
    assert _run(["--claude-md", claude_md, "sweep", "--no-ledger"]) == 1
    out = capsys.readouterr().out
    assert "LIVE_NOT_ON_ROW: ktp_cvar.amxx" in out and "NOT read" in out


# -- the fleet read --------------------------------------------------------

BASES = {"engine_i486.so": "serverfiles", "ktp_cvar.amxx": PLUGINS}


def test_host_command_is_read_only_and_covers_every_swap_dir():
    cmd = wl.host_command([27015, 27016], BASES)
    for d in wl.SWAP_DIRS:
        assert f"{d}/*.new" in cmd
    assert "serverfiles/engine_i486.so" in cmd and f"{PLUGINS}/ktp_cvar.amxx" in cmd
    for verb in (" rm ", " mv ", " cp ", "chmod", "tee", " > ", "restart"):
        assert verb not in cmd


def test_parse_host_output():
    text = "\n".join([
        "@@ 27015",
        f"{ENGINE}  serverfiles/engine_i486.so",
        f"{CVAR_738}  {PLUGINS}/ktp_cvar.amxx.new",
        "@@ 27016",
        f"{ENGINE}  serverfiles/engine_i486.so",
        f"{CVAR_737}  {PLUGINS}/ktp_cvar.amxx",
        "@@ 27017",
        "@@NODIR",
        "@@ 27018",
        wl._DONE,
    ])
    r = wl.FleetRead()
    wl.parse_host_output("dallas", [27015, 27016, 27017, 27018, 27019], text, BASES, r)
    assert r.live["ktp_cvar.amxx"] == {"dallas:27015": None, "dallas:27016": CVAR_737}
    assert r.staged == {"ktp_cvar.amxx": {"dallas:27015": CVAR_738}}
    assert set(r.errors) == {"dallas:27017", "dallas:27018", "dallas:27019"}


def test_truncated_host_output_is_an_error_not_an_absence():
    r = wl.FleetRead()
    wl.parse_host_output("denver", [27015], f"@@ 27015\n{ENGINE}  serverfiles/engine_i486.so\n", BASES, r)
    assert "denver" in r.errors and r.live == {}
