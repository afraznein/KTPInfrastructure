"""Unit tests for stage-runner.py's `--show` manifest-vs-disk flagging.

`MANIFEST DISAGREES WITH DISK` used to be unscoped, and two classes of artifact
on that runner keep their record somewhere other than this manifest. The Tier-2
workflow compiles its own copy of the plugins it gates on and installs each over
whatever was staged, baking a fresh per-minute BUILD_TIME every run; and
`sync-runner-stack.py` mirrors the stack files from the fleet, where byte
equality with the fleet is the point. For both, the warning fired on every run
of `--show` and the reader who chased it found nothing wrong — one of them got
written up as a three-artifact defect on a healthy runner.

These tests pull in both directions: each noise class must be suppressed, and an
artifact in neither class must still report a real disagreement.

Both scopes are DERIVED — the workflow's install destinations, and the drift
checker's own lists — rather than listed in the script, so each parse gets its
own tests. The over-matching direction is the dangerous one: a pattern that also
matched the workflow's `test -f` verify step would claim artifacts the workflow
never installs and silence the only line worth printing.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# stage-runner.py sys.exit()s at import when paramiko is absent, which pytest
# surfaces as a collection INTERNALERROR that takes the whole tier-1 job down.
# Nothing under test here touches paramiko, so a stub is enough.
if "paramiko" not in sys.modules:
    try:
        import paramiko  # noqa: F401
    except ImportError:
        sys.modules["paramiko"] = types.ModuleType("paramiko")

REPO = Path(__file__).parents[2]
SCRIPT = REPO / "scripts" / "stage-runner.py"
SPEC = importlib.util.spec_from_file_location("stage_runner_show", SCRIPT)
assert SPEC and SPEC.loader
stage_runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage_runner)

WORKFLOW = REPO / ".github" / "workflows" / "tier2-integration.yml"

MD5_A = "4b3e524579e2b481245fccdaf94565f7"
MD5_B = "9a71ed2e184b54fa33136d0920919095"


# ---------------------------------------------------------------------------
# Deriving the scope from the workflow
# ---------------------------------------------------------------------------

def test_workflow_rebuilt_matches_the_install_destinations(tmp_path):
    wf = tmp_path / "tier2.yml"
    wf.write_text(
        '          install -D "$WORK/Alpha.amxx" \\\n'
        '            "$SF/dod/addons/ktpamx/plugins/Alpha.amxx"\n'
        '          install -D "$WORK/Beta.amxx" "$SF/dod/addons/ktpamx/plugins/Beta.amxx"\n',
        encoding="utf-8",
    )
    assert stage_runner.workflow_rebuilt(wf) == {"Alpha.amxx", "Beta.amxx"}


def test_workflow_rebuilt_ignores_a_path_the_workflow_only_checks(tmp_path):
    """The over-matching direction. `test -f` proves the artifact is expected,
    not that the workflow replaced it — claiming it would suppress a real
    disagreement on the one plugin nothing rebuilds."""
    wf = tmp_path / "tier2.yml"
    wf.write_text(
        '          install -D "$WORK/Alpha.amxx" "$SF/dod/addons/ktpamx/plugins/Alpha.amxx"\n'
        '          test -f "$SF/dod/addons/ktpamx/plugins/Gamma.amxx" || exit 1\n'
        '          md5sum "$SF/dod/addons/ktpamx/modules/dodx_ktp_i386.so"\n',
        encoding="utf-8",
    )
    assert stage_runner.workflow_rebuilt(wf) == {"Alpha.amxx"}


def test_workflow_rebuilt_is_none_when_unreadable(tmp_path):
    """Distinct from the empty set on purpose: an unreadable workflow must not
    read as "the workflow rebuilds nothing" and silence the flag."""
    assert stage_runner.workflow_rebuilt(tmp_path / "absent.yml") is None
    assert stage_runner.workflow_rebuilt(tmp_path) is None


def test_real_workflow_parses_and_scopes_a_strict_subset():
    """Against the committed workflow, so a step renamed or a plugin added
    cannot leave the scope silently empty. Asserts the shape, not a roster: the
    set must be non-empty and must not swallow every tracked test-mode plugin,
    or the flag could never fire again."""
    rebuilt = stage_runner.workflow_rebuilt(WORKFLOW)
    assert rebuilt, f"no install destinations parsed out of {WORKFLOW}"
    assert rebuilt & stage_runner.TESTMODE_PLUGINS, (
        "nothing the manifest tracks reads as workflow-rebuilt, so the scope "
        "changes no line `--show` prints"
    )
    assert not stage_runner.TESTMODE_PLUGINS <= rebuilt, (
        "every tracked test-mode plugin reads as workflow-rebuilt; the "
        "disagreement line can no longer fire for anything"
    )


# ---------------------------------------------------------------------------
# Deriving the fleet-mirror scope from the drift checker
# ---------------------------------------------------------------------------

def test_fleet_mirrored_is_the_drift_checkers_own_lists_by_basename():
    """The three artifacts whose manifest drift was mistaken for a defect are
    all in here — their record is the fleet, not this manifest."""
    mirrored = stage_runner.fleet_mirrored()
    assert mirrored, "no fleet-mirrored basenames read out of the drift checker"
    for owned in ("ktp_cvar.amxx", "KTPGrenadeLoadout.amxx", "dodx_ktp_i386.so"):
        assert owned in mirrored
    assert "/" not in "".join(mirrored), "paths must be reduced to basenames"


def test_fleet_mirrored_is_none_when_the_drift_checker_cannot_be_loaded(tmp_path):
    """Same distinction as the workflow side, and it needed its own test: a
    `None`-vs-empty bug here is invisible to any test that hands `disk_flag` a
    `None` directly."""
    assert stage_runner.fleet_mirrored(tmp_path / "absent.py") is None
    assert stage_runner.fleet_mirrored(tmp_path) is None
    broken = tmp_path / "broken.py"
    broken.write_text("STACK_FILES = ['a']\n", encoding="utf-8")  # no PLUGINS_STRICT
    assert stage_runner.fleet_mirrored(broken) is None


def test_fleet_mirrored_excludes_the_test_mode_builds():
    """The sync tool refuses to touch these, so the manifest IS their record and
    a disagreement on one is real. Overlap here would silence that."""
    mirrored = stage_runner.fleet_mirrored()
    assert not (mirrored & stage_runner.TESTMODE_PLUGINS)


# ---------------------------------------------------------------------------
# The flag itself
# ---------------------------------------------------------------------------

def test_agreement_is_silent():
    assert stage_runner.disk_flag("Alpha.amxx", MD5_A, MD5_A, {"Alpha.amxx"}) == ""
    assert stage_runner.disk_flag("Gamma.amxx", MD5_A, MD5_A, set()) == ""


def test_absent_outranks_everything():
    assert "not on the runner" in stage_runner.disk_flag("Gamma.amxx", "ABSENT", MD5_A, set())
    assert "not on the runner" in stage_runner.disk_flag("Gamma.amxx", "ABSENT", "-", None)


def test_unstaged_artifact_is_not_called_a_disagreement():
    """No manifest md5 means nobody staged it, so there is nothing to disagree
    with — printing a disagreement there is what made `--show` unreadable. It is
    still named, because "absent" and "deliberately absent" used to print the
    same blank."""
    flag = stage_runner.disk_flag("Gamma.amxx", MD5_A, "-", set())
    assert "MANIFEST DISAGREES" not in flag
    assert "no manifest record, and nothing else installs it" in flag
    flag = stage_runner.disk_flag("Alpha.amxx", MD5_A, "-", {"Alpha.amxx"})
    assert "MANIFEST DISAGREES" not in flag
    assert "workflow installs it every run" in flag


def test_disagreement_still_reports_for_an_artifact_in_neither_class():
    flag = stage_runner.disk_flag("Gamma.amxx", MD5_A, MD5_B, {"Alpha.amxx"}, {"Beta.amxx"})
    assert "MANIFEST DISAGREES WITH DISK" in flag


def test_disagreement_is_suppressed_for_a_workflow_rebuilt_artifact():
    flag = stage_runner.disk_flag("Alpha.amxx", MD5_A, MD5_B, {"Alpha.amxx"})
    assert "MANIFEST DISAGREES WITH DISK" not in flag
    assert "rebuilt per run" in flag


def test_disagreement_is_suppressed_for_a_fleet_mirror():
    flag = stage_runner.disk_flag("Beta.amxx", MD5_A, MD5_B, {"Alpha.amxx"}, {"Beta.amxx"})
    assert "MANIFEST DISAGREES WITH DISK" not in flag
    assert "fleet mirror" in flag


def test_workflow_rebuilt_wins_when_an_artifact_is_in_both():
    """Disjoint by construction today, and the sync tool asserts that. If they
    ever overlap, disk holds whatever the last run installed."""
    flag = stage_runner.disk_flag("Alpha.amxx", MD5_A, MD5_B, {"Alpha.amxx"}, {"Alpha.amxx"})
    assert "rebuilt per run" in flag


def test_unreadable_workflow_keeps_the_warning_and_says_so():
    """Fail towards printing. The scope is an improvement on the warning, not a
    precondition for it."""
    flag = stage_runner.disk_flag("Alpha.amxx", MD5_A, MD5_B, None)
    assert "MANIFEST DISAGREES WITH DISK" in flag
    assert "could not read the Tier-2 workflow" in flag


def test_unreadable_drift_checker_keeps_the_warning_and_says_so():
    flag = stage_runner.disk_flag("Beta.amxx", MD5_A, MD5_B, {"Alpha.amxx"}, None)
    assert "MANIFEST DISAGREES WITH DISK" in flag
    assert "could not read the drift checker" in flag


# ---------------------------------------------------------------------------
# --check, and the suite's on-runner check: unexplained vs deliberate
# ---------------------------------------------------------------------------

import runner_manifest as rm  # noqa: E402  -- stage-runner put scripts/ on sys.path


def test_deliberate_classes_are_not_unexplained():
    for kind in (rm.AGREE, rm.WORKFLOW, rm.MIRROR, rm.UNRECORDED_REBUILT, rm.ABSENT_REBUILT):
        assert kind not in rm.UNEXPLAINED


def test_every_kind_has_flag_text():
    kinds = {v for k, v in vars(rm).items() if k.isupper() and isinstance(v, str)
             and v in rm._FLAG_TEXT}
    assert kinds == set(rm._FLAG_TEXT)


def test_check_verdict_quiet_on_nothing_unexplained():
    status, line = stage_runner.check_verdict([])
    assert status == 0 and "CHECK OK" in line


def test_check_verdict_fails_and_names_each_row():
    status, line = stage_runner.check_verdict([("Gamma.amxx", rm.DRIFT), ("Delta.amxx", rm.ABSENT)])
    assert status == 1
    assert "Gamma.amxx: drift" in line and "Delta.amxx: absent" in line


def test_fleet_mirrored_needs_no_paramiko(tmp_path):
    """The suite's venv has no paramiko and the drift checker exits at import
    without it, so the list must be PARSED. A checker whose top level would
    exit still yields its lists."""
    checker = tmp_path / "drift.py"
    checker.write_text(
        "import sys\nsys.exit(2)\n"
        "STACK_FILES = ['engine_i486.so', 'dod/addons/ktpamx/modules/dodx_ktp_i386.so']\n"
        "PLUGINS_STRICT = ['dod/addons/ktpamx/plugins/ktp_cvar.amxx']\n",
        encoding="utf-8",
    )
    assert rm.fleet_mirrored(checker) == {"engine_i486.so", "dodx_ktp_i386.so", "ktp_cvar.amxx"}


def _runner(tmp_path, files):
    tree = tmp_path / "serverfiles"
    for name, body in files.items():
        p = tree / rm.artifact_dir(name) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    return tree


def _md5(b):
    import hashlib
    return hashlib.md5(b).hexdigest()


def test_classify_local_quiet_on_the_two_deliberate_classes(tmp_path):
    """Positive control: today's runner shape — a workflow-rebuilt plugin and a
    fleet mirror both differ from the manifest, and one staged plugin agrees."""
    tree = _runner(tmp_path, {
        "Rebuilt.amxx": b"fresh build", "Mirror.so": b"fleet bytes", "Staged.amxx": b"staged",
    })
    manifest = {
        "Rebuilt.amxx": {"md5": _md5(b"what was staged")},
        "Mirror.so": {"md5": _md5(b"older fleet bytes")},
        "Staged.amxx": {"md5": _md5(b"staged")},
    }
    rows = rm.classify_local(str(tree), manifest, {"Rebuilt.amxx"}, {"Mirror.so"})
    kinds = {n: k for n, k, _, _ in rows}
    assert kinds == {"Rebuilt.amxx": rm.WORKFLOW, "Mirror.so": rm.MIRROR, "Staged.amxx": rm.AGREE}
    assert not [r for r in rows if r[1] in rm.UNEXPLAINED]


def test_classify_local_fails_on_an_artifact_in_neither_class(tmp_path):
    """Negative control: the same runner with the staged plugin overwritten
    behind the manifest's back must fail."""
    tree = _runner(tmp_path, {"Staged.amxx": b"something else wrote this"})
    manifest = {"Staged.amxx": {"md5": _md5(b"staged")}, "Gone.amxx": {"md5": _md5(b"x")}}
    rows = rm.classify_local(str(tree), manifest, {"Rebuilt.amxx"}, {"Mirror.so"})
    kinds = {n: k for n, k, _, _ in rows}
    assert kinds == {"Staged.amxx": rm.DRIFT, "Gone.amxx": rm.ABSENT}
    assert all(k in rm.UNEXPLAINED for k in kinds.values())


def test_classify_local_fails_closed_when_a_scope_is_unreadable(tmp_path):
    tree = _runner(tmp_path, {"Mirror.so": b"fleet bytes"})
    manifest = {"Mirror.so": {"md5": _md5(b"older")}}
    assert rm.classify_local(str(tree), manifest, None, {"Mirror.so"})[0][1] == rm.UNKNOWN_WORKFLOW
    assert rm.classify_local(str(tree), manifest, set(), None)[0][1] == rm.UNKNOWN_MIRROR


def test_classify_local_derives_scopes_from_the_repo_by_default(tmp_path):
    """Default call reads the committed workflow and drift checker, so a real
    fleet-mirror basename is quiet without being passed in."""
    tree = _runner(tmp_path, {"dodx_ktp_i386.so": b"new fleet pin"})
    rows = rm.classify_local(str(tree), {"dodx_ktp_i386.so": {"md5": _md5(b"old")}})
    assert rows[0][1] == rm.MIRROR
