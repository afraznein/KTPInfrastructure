"""The build base a wave records beside each artifact's md5.

Three of eleven fleet artifacts had a build base recorded anywhere, so "has this
moved since?" could not be answered exactly for the other eight -- and it never
will be for those, because none of these artifacts is byte-reproducible. `.amxx`
bakes a per-minute BUILD_TIME and ReHLDS bakes a build-id and `__DATE__`, so
rebuilding candidate commits and comparing md5s returns a MISMATCH for the base
that actually built the file. Stage time is the only moment it is knowable.

Nothing here touches the fleet or the network. `stage-wave.py` imports paramiko
at module scope (and `sys.exit(1)` if it is absent), and the unit lane installs
only pytest + jsonschema -- so paramiko is stubbed before the load. The stub is
never called: every case here is argument parsing and the ledger write.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_ROOT, "scripts")


def _load(mod_name, filename):
    spec = importlib.util.spec_from_file_location(mod_name, os.path.join(_SCRIPTS, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _stub_paramiko():
    if "paramiko" in sys.modules:
        return
    stub = types.ModuleType("paramiko")
    stub.SSHClient = object
    stub.AutoAddPolicy = object
    sys.modules["paramiko"] = stub


_stub_paramiko()
wl = _load("ktp_wave_ledger", "ktp-wave-ledger.py")
sw = _load("stage_wave", "stage-wave.py")

MD5 = "bf07ff9bf61e11edbc4d64b78abc0bff"      # KTPMatchHandler 0.10.170, as shipped
BASE = "afraznein/KTPMatchHandler@b891b0e"


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("KTP_WAVE_LEDGER_DIR", str(tmp_path / "waves"))


class FakeArtifact:
    """Just the fields the gate reads off deploy-to-fleet's Artifact."""

    def __init__(self, basename, local_path="/nope/x.amxx"):
        self.basename = basename
        self.local_path = local_path
        self.md5 = MD5
        self.remote_dir = "serverfiles/dod/addons/ktpamx/plugins"
        self.size = 1


# -- parsing ---------------------------------------------------------------

def test_parses_a_repo_qualified_base():
    assert sw.parse_base_pins([f"KTPMatchHandler.amxx={BASE}"]) == {"KTPMatchHandler.amxx": BASE}


@pytest.mark.parametrize("base", [
    "b891b0e",                                  # bare short sha
    "b891b0e26f2141e0aa2f0e3f2d3f4a5b6c7d8e9f",  # full sha
    "afraznein/KTP-ReHLDS@448b4f9",             # a hyphen in the repo name
    "afraznein/KTPCvarChecker@27223fa-dirty",   # built from an unclean tree
])
def test_accepted_base_shapes(base):
    assert sw.parse_base_pins([f"x.amxx={base}"])["x.amxx"] == base


@pytest.mark.parametrize("bad", [
    "x.amxx=main",                # a branch name is not a build base
    "x.amxx=b891b0",              # 6 hex: too short to be unambiguous
    "x.amxx=zzzzzzz",             # not hex
    "x.amxx=b891b0e-wip",         # only -dirty is a legal suffix
    "x.amxx=",                    # empty
    "KTPMatchHandler.amxx",       # no '='
])
def test_rejected_base_shapes(bad):
    with pytest.raises(ValueError):
        sw.parse_base_pins([bad])


def test_a_branch_name_is_refused_because_it_is_not_a_build_base():
    """`main` moves. Recording it answers "has this moved?" with "ask again
    later", which is the same as not recording it -- only harder to spot."""
    with pytest.raises(ValueError, match="not a build base"):
        sw.parse_base_pins(["x.amxx=main"])


def test_the_parser_and_the_record_share_one_definition():
    """A shape stage-wave accepts must be a shape the ledger will store, or the
    two drift and a wave passes the gate and then fails to record."""
    for base in ["b891b0e", BASE, "afraznein/KTPCvarChecker@27223fa-dirty"]:
        assert sw.parse_base_pins([f"x.amxx={base}"])
        wl.record_wave([{"basename": "x.amxx", "md5": MD5, "base": base}],
                       hosts=["atlanta"], targets=24)


# -- the record ------------------------------------------------------------

def test_the_base_reaches_the_ledger_file():
    """The point of the whole change: the fact is on disk, not in stdout."""
    path = wl.record_wave([{"basename": "KTPMatchHandler.amxx", "md5": MD5,
                            "remote_dir": "plugins", "base": BASE}],
                          hosts=["atlanta"], targets=24)
    entry = json.loads(open(path, encoding="utf-8").read())
    assert entry["artifacts"][0]["base"] == BASE


def test_a_malformed_base_is_refused_by_the_record_too():
    with pytest.raises(ValueError, match="not a build base"):
        wl.record_wave([{"basename": "x.amxx", "md5": MD5, "base": "main"}],
                       hosts=["atlanta"], targets=24)


def test_a_wave_with_no_base_records_the_field_as_null_not_absent():
    """`--allow-missing-base` has to leave a positive "nobody recorded this",
    distinguishable from a ledger entry written before the field existed."""
    path = wl.record_wave([{"basename": "x.amxx", "md5": MD5}], hosts=["atlanta"], targets=24)
    entry = json.loads(open(path, encoding="utf-8").read())
    assert "base" in entry["artifacts"][0]
    assert entry["artifacts"][0]["base"] is None


def test_status_says_unrecoverable_rather_than_leaving_it_blank(capsys):
    wl.record_wave([{"basename": "x.amxx", "md5": MD5}], hosts=["atlanta"], targets=24)
    assert wl.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "NOT RECORDED" in out
    assert "not byte-reproducible" in out


def test_status_prints_a_recorded_base(capsys):
    wl.record_wave([{"basename": "x.amxx", "md5": MD5, "base": BASE}],
                   hosts=["atlanta"], targets=24)
    assert wl.main(["status"]) == 0
    assert BASE in capsys.readouterr().out


# -- the record CLI --------------------------------------------------------

def test_record_cli_attaches_the_base_to_the_right_artifact(capsys):
    rc = wl.main(["record",
                  "-a", f"KTPMatchHandler.amxx={MD5}:plugins",
                  "-a", f"ktp_cvar.amxx={MD5}:plugins",
                  "--base", f"KTPMatchHandler.amxx={BASE}",
                  "--hosts", "atlanta", "--targets", "24"])
    assert rc == 0
    path = capsys.readouterr().out.strip()
    arts = {a["basename"]: a for a in json.loads(open(path, encoding="utf-8").read())["artifacts"]}
    assert arts["KTPMatchHandler.amxx"]["base"] == BASE
    assert arts["ktp_cvar.amxx"]["base"] is None


def test_record_cli_refuses_a_base_for_an_artifact_not_in_the_wave():
    """A typo in the one field nobody can reconstruct has to be fatal: silently
    dropping it records exactly the absence this whole change exists to end."""
    with pytest.raises(SystemExit):
        wl.main(["record", "-a", f"KTPMatchHandler.amxx={MD5}:plugins",
                 "--base", f"KTPMatchHandlr.amxx={BASE}",
                 "--hosts", "atlanta", "--targets", "24"])


# -- the gate --------------------------------------------------------------

def _gate(monkeypatch, argv, artifacts):
    """Run main() up to the point the base gate decides, with the fleet unreachable.

    Everything before the gate is stubbed out; anything after it would need the
    network, and none of these cases is expected to get that far.
    """
    monkeypatch.setattr(sw.ledger, "gate", lambda *a, **k: sw.ledger.GateResult("clear", []))
    monkeypatch.setattr(sw.d2f, "build_artifacts", lambda files, override_remote: artifacts)
    monkeypatch.setattr(sys, "argv", ["stage-wave.py", "--allow-existing-new", "--dry-run"] + argv)
    return sw.main()


def test_missing_base_is_fatal_by_default(monkeypatch, capsys):
    with pytest.raises(SystemExit) as ex:
        _gate(monkeypatch, ["-f", "x.amxx"], [FakeArtifact("x.amxx")])
    err = capsys.readouterr().err
    assert "no --base" in err
    assert "MISMATCH for the base" in err
    assert "--allow-missing-base" in str(ex.value)


def test_the_opt_out_stages_but_says_the_loss_is_permanent(monkeypatch, capsys):
    _gate(monkeypatch, ["-f", "x.amxx", "--allow-missing-base"], [FakeArtifact("x.amxx")])
    out = capsys.readouterr().out
    assert "WARNING: --allow-missing-base" in out
    assert "NOT RECORDED" in out


def test_a_supplied_base_clears_the_gate(monkeypatch, capsys):
    _gate(monkeypatch, ["-f", "x.amxx", "--base", f"x.amxx={BASE}"], [FakeArtifact("x.amxx")])
    out = capsys.readouterr().out
    assert f"built from {BASE}" in out
    assert "WARNING: --allow-missing-base" not in out


def test_one_artifact_without_a_base_blocks_a_multi_artifact_wave(monkeypatch, capsys):
    """The 2026-09-08 shape: two artifacts in one deliberate stack. A gate that
    passes on the strength of the pinned one is not a gate."""
    with pytest.raises(SystemExit):
        _gate(monkeypatch,
              ["-f", "a.amxx", "-f", "b.amxx", "--base", f"a.amxx={BASE}"],
              [FakeArtifact("a.amxx"), FakeArtifact("b.amxx")])
    err = capsys.readouterr().err
    assert "b.amxx" in err
    assert "no --base (build base) for: b.amxx" in err


def test_a_base_naming_an_artifact_not_in_the_wave_is_fatal(monkeypatch, capsys):
    with pytest.raises(SystemExit) as ex:
        _gate(monkeypatch, ["-f", "a.amxx", "--base", f"a.amxx={BASE}",
                            "--base", f"typo.amxx={BASE}"], [FakeArtifact("a.amxx")])
    assert "not in this wave: typo.amxx" in str(ex.value)


def test_a_malformed_base_is_fatal_before_anything_is_staged(monkeypatch):
    with pytest.raises(SystemExit) as ex:
        _gate(monkeypatch, ["-f", "a.amxx", "--base", "a.amxx=main"], [FakeArtifact("a.amxx")])
    assert "not a build base" in str(ex.value)


# -- detection is a HINT, never a recorded value ----------------------------

def test_detect_returns_none_outside_a_repo(tmp_path):
    assert sw.detect_build_base(str(tmp_path / "x.amxx")) is None


def test_detect_reads_a_real_repo_and_flags_a_dirty_tree(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()

    def git(*a):
        return subprocess.run(("git", "-C", str(repo)) + a, capture_output=True, text=True)

    if git("init", "-q").returncode != 0:
        pytest.skip("git unavailable")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    git("remote", "add", "origin", "https://github.com/afraznein/KTPMatchHandler.git")
    (repo / "a.txt").write_text("1", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "x")

    clean = sw.detect_build_base(str(repo / "art.amxx"))
    assert clean is not None
    assert clean.startswith("afraznein/KTPMatchHandler@")
    assert not clean.endswith("-dirty")
    # ...and whatever it produced must be a shape the record would accept, or
    # the hint sends the operator to a flag that then rejects it.
    assert sw.parse_base_pins([f"x.amxx={clean}"])

    (repo / "a.txt").write_text("2", encoding="utf-8")
    assert sw.detect_build_base(str(repo / "art.amxx")).endswith("-dirty")


def test_detection_is_never_used_as_the_recorded_value(monkeypatch, capsys):
    """A detected base is offered in the error text and nowhere else. Recording a
    guess would read exactly like a supplied fact -- the artifact can predate the
    checkout it sits in, and nothing about the file says so."""
    monkeypatch.setattr(sw, "detect_build_base", lambda p: "afraznein/Wrong@0000000")
    with pytest.raises(SystemExit):
        _gate(monkeypatch, ["-f", "x.amxx"], [FakeArtifact("x.amxx")])
    cap = capsys.readouterr()
    assert "afraznein/Wrong@0000000" in cap.err          # offered
    assert "CHECK it is what you built" in cap.err
    assert wl.load_waves() == []                          # and never written
