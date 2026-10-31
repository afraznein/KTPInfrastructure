"""Unit tests for stage-runner.py's `--show` manifest-vs-disk flagging.

`MANIFEST DISAGREES WITH DISK` used to be unscoped. The Tier-2 workflow compiles
its own copy of the plugins it gates on and installs each over whatever was
staged, baking a fresh per-minute BUILD_TIME every run — so for those artifacts
the staged md5 can never match disk, the warning fired on every run of `--show`,
and the reader who chased it found nothing wrong. These tests pull in both
directions: the noise class must be suppressed, and an artifact the workflow
leaves alone must still report a real disagreement.

The scope is DERIVED from `.github/workflows/tier2-integration.yml` rather than
listed in the script, so the parse gets its own tests — including the
over-matching direction, which is the dangerous one: a pattern that also matched
the workflow's `test -f` verify step would claim artifacts the workflow never
installs and silence the one line worth printing.
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
# The flag itself
# ---------------------------------------------------------------------------

def test_agreement_is_silent():
    assert stage_runner.disk_flag("Alpha.amxx", MD5_A, MD5_A, {"Alpha.amxx"}) == ""
    assert stage_runner.disk_flag("Gamma.amxx", MD5_A, MD5_A, set()) == ""


def test_absent_outranks_everything():
    assert "not on the runner" in stage_runner.disk_flag("Gamma.amxx", "ABSENT", MD5_A, set())
    assert "not on the runner" in stage_runner.disk_flag("Gamma.amxx", "ABSENT", "-", None)


def test_unstaged_artifact_is_not_a_disagreement():
    """No manifest md5 means nobody staged it, so there is nothing to disagree
    with — printing a disagreement there is what made `--show` unreadable."""
    assert stage_runner.disk_flag("Gamma.amxx", MD5_A, "-", set()) == ""


def test_disagreement_still_reports_for_an_artifact_the_workflow_leaves_alone():
    flag = stage_runner.disk_flag("Gamma.amxx", MD5_A, MD5_B, {"Alpha.amxx"})
    assert "MANIFEST DISAGREES WITH DISK" in flag


def test_disagreement_is_suppressed_for_a_workflow_rebuilt_artifact():
    flag = stage_runner.disk_flag("Alpha.amxx", MD5_A, MD5_B, {"Alpha.amxx"})
    assert "MANIFEST DISAGREES WITH DISK" not in flag
    assert "rebuilt per run" in flag


def test_unreadable_workflow_keeps_the_warning_and_says_so():
    """Fail towards printing. The scope is an improvement on the warning, not a
    precondition for it."""
    flag = stage_runner.disk_flag("Alpha.amxx", MD5_A, MD5_B, None)
    assert "MANIFEST DISAGREES WITH DISK" in flag
    assert "could not read the Tier-2 workflow" in flag
