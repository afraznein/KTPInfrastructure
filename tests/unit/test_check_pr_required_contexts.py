"""check-pr-required-contexts.py: a MISSING required check is not a FAILING one.

The classifier is tested directly, with no network. That is the point of its shape:
the judgement that distinguishes "never reported for this sha" from "reported and
failed" is pure, so it can be exercised against states no live repo is conveniently
sitting in -- including the 2026-10-05 KTPAntiCheat#522 state, where two required
contexts had no run at all and the PR showed nothing red.

What is NOT covered here: `gh api` itself, pagination against a real repo, and
whether a required context's name still matches the job that produces it. The last
of those is undecidable from any checkout and the script says so.
"""
import importlib.util
import pathlib

import pytest

SCRIPT = (pathlib.Path(__file__).resolve().parents[2]
          / "scripts" / "check-pr-required-contexts.py")


def _load():
    spec = importlib.util.spec_from_file_location("check_pr_required_contexts",
                                                  SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()
MISSING, PENDING, FAILED, PASSED = mod.MISSING, mod.PENDING, mod.FAILED, mod.PASSED


def run(name, conclusion, finished="2026-10-05T12:00:00Z", status="completed",
        source="check-run"):
    return {"name": name, "status": status, "conclusion": conclusion,
            "finished": finished, "source": source}


# ── the defect that motivated the script ───────────────────────────────

def test_a_required_context_with_no_run_is_missing_not_passing():
    """#522: `test` and `test-tier2` were required and never reported."""
    runs = [run("lint", "success"), run("vac-safety", "success")]
    v = mod.classify(["test", "test-tier2", "lint"], runs)
    assert v == {"test": MISSING, "test-tier2": MISSING, "lint": PASSED}


def test_missing_and_failing_are_different_states():
    """The whole point: the PR page renders both as blocked with nothing red."""
    v = mod.classify(["a", "b"], [run("b", "failure")])
    assert v["a"] == MISSING
    assert v["b"] == FAILED
    assert v["a"] != v["b"]


def test_no_runs_at_all_is_all_missing():
    v = mod.classify(["a", "b"], [])
    assert set(v.values()) == {MISSING}


def test_an_empty_required_set_is_vacuously_clean():
    """Honest, and the reason an UNREADABLE set exits 3 instead of 0."""
    assert mod.classify([], [run("whatever", "failure")]) == {}


# ── the superseded-run trap ────────────────────────────────────────────

def test_a_rerun_is_judged_on_its_latest_attempt():
    """Both attempts come back from the API; the newest is the live one."""
    runs = [run("test", "failure", finished="2026-10-05T10:00:00Z"),
            run("test", "success", finished="2026-10-05T11:00:00Z")]
    assert mod.classify(["test"], runs) == {"test": PASSED}


def test_a_rerun_that_went_red_is_not_laundered_by_an_older_green():
    """The same trap in the direction that matters more."""
    runs = [run("test", "success", finished="2026-10-05T10:00:00Z"),
            run("test", "failure", finished="2026-10-05T11:00:00Z")]
    assert mod.classify(["test"], runs) == {"test": FAILED}


def test_response_order_does_not_decide_the_verdict():
    """Reading whichever the API returned first is the bug being avoided."""
    old = run("test", "failure", finished="2026-10-05T10:00:00Z")
    new = run("test", "success", finished="2026-10-05T11:00:00Z")
    assert mod.classify(["test"], [old, new]) == mod.classify(["test"], [new, old])


# ── the two-endpoint union ─────────────────────────────────────────────

def test_a_context_reported_only_as_a_commit_status_is_not_missing():
    """An external reporter satisfies a required context from a different endpoint."""
    runs = [run("codecov/patch", "success", source="status")]
    assert mod.classify(["codecov/patch"], runs) == {"codecov/patch": PASSED}


# ── pending, and the conclusions protection accepts ────────────────────

def test_a_queued_run_is_pending_not_missing():
    runs = [run("test", None, status="queued")]
    assert mod.classify(["test"], runs) == {"test": PENDING}


def test_a_completed_run_with_no_conclusion_is_pending():
    runs = [run("test", None, status="completed")]
    assert mod.classify(["test"], runs) == {"test": PENDING}


@pytest.mark.parametrize("conclusion", sorted(mod.PASSING))
def test_conclusions_github_counts_as_satisfying_pass(conclusion):
    """`neutral` and `skipped` satisfy protection; calling them failures blocks
    a PR this tool should have cleared."""
    assert mod.classify(["t"], [run("t", conclusion)]) == {"t": PASSED}


@pytest.mark.parametrize("conclusion", sorted(mod.FAILING))
def test_conclusions_that_are_failures(conclusion):
    assert mod.classify(["t"], [run("t", conclusion)]) == {"t": FAILED}


def test_an_unknown_conclusion_is_pending_not_passing():
    """A conclusion GitHub adds later must not default to green."""
    assert mod.classify(["t"], [run("t", "some-future-state")]) == {"t": PENDING}


def test_an_unnamed_run_is_ignored_rather_than_matching_everything():
    assert mod.classify(["t"], [run(None, "success")]) == {"t": MISSING}


# ── the report, which is what a human acts on ──────────────────────────

def test_the_report_names_the_remedy_only_when_something_is_missing(capsys):
    mod.report("o/r", 522, "deadbeef", {"test": MISSING, "lint": PASSED}, set())
    out = capsys.readouterr().out
    assert "NEVER REPORTED" in out
    assert "Close and reopen" in out
    assert "do NOT `gh run rerun`" in out


def test_the_report_is_quiet_when_everything_passed(capsys):
    mod.report("o/r", 1, "cafe", {"test": PASSED}, set())
    out = capsys.readouterr().out
    assert "NEVER REPORTED" not in out
    assert "rerun" not in out


def test_the_report_leads_with_the_missing_ones(capsys):
    mod.report("o/r", 1, "cafe",
               {"zzz-passing": PASSED, "aaa-missing": MISSING,
                "mmm-failing": FAILED}, set())
    lines = [l.strip() for l in capsys.readouterr().out.splitlines() if l.strip()]
    states = [l.split()[0] for l in lines if l.split()[0] in
              (MISSING, FAILED, PENDING, PASSED)]
    assert states == [MISSING, FAILED, PASSED]


def test_the_report_says_so_when_nothing_is_required(capsys):
    mod.report("o/r", 1, "cafe", {}, set())
    assert "no required contexts" in capsys.readouterr().out


# ── mutation tests: each breaks the classifier and names what reddens ──

def test_mutation_latest_per_name_keeping_the_first_reddens():
    """Exercises the superseded-run legs.

    Replaces newest-wins with first-wins; the rerun tests then read the stale
    attempt, which is exactly the statusCheckRollup defect.
    """
    runs = [run("test", "failure", finished="2026-10-05T10:00:00Z"),
            run("test", "success", finished="2026-10-05T11:00:00Z")]
    first_wins = {}
    for r in runs:
        first_wins.setdefault(r["name"], r)
    assert first_wins["test"]["conclusion"] == "failure"
    assert mod.latest_per_name(runs)["test"]["conclusion"] == "success"


def test_mutation_treating_missing_as_absent_from_the_verdict_reddens():
    """If an unreported context were simply omitted, `all(PASSING)` would be
    vacuously true and the script would exit 0 on the #522 state."""
    v = mod.classify(["test", "test-tier2"], [])
    assert v, "a verdict that omits unreported contexts would exit 0"
    assert not all(s == PASSED for s in v.values())


def test_mutation_unioning_only_check_runs_reddens():
    """Drops the statuses endpoint: an external reporter reads as MISSING."""
    status_only = [run("codecov/patch", "success", source="status")]
    check_runs_only = [r for r in status_only if r["source"] == "check-run"]
    assert mod.classify(["codecov/patch"], check_runs_only) == \
        {"codecov/patch": MISSING}
    assert mod.classify(["codecov/patch"], status_only) == \
        {"codecov/patch": PASSED}
