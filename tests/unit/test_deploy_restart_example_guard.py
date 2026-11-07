"""`deploy-restart-script.py`'s content guard: canonical vs the tracked `.example`.

The canonical `scripts/ktp-scheduled-restart.sh` is gitignored and untracked, so
`git status` can never flag drift in it and the deploy ships whatever is sitting
there. Refreshing it by hand fixed that once; nothing prevented a recurrence.
The guard makes the recurrence impossible to deploy through.

What it enforces is the invariant docs/runbooks/SCHEDULED_RESTART_LINEAGES.md
already ruled: L2 (the canonical) is L3 (the `.example`) with two placeholders
filled. Everything else must match, in both directions — `.example` has been
*ahead* of the fleet, which is the drift the real-file case below carries.

⛔ The allowlisted values are live Discord channel IDs in a public repo. Every
fixture here invents its own; none is read from, or compared against, a real
one, and the guard's own output is asserted to carry keys and line numbers only.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "deploy-restart-script.py"
EXAMPLE = REPO / "scripts" / "ktp-scheduled-restart.sh.example"
CANONICAL = REPO / "scripts" / "ktp-scheduled-restart.sh"

# Invented, and shaped like the real thing only in that they are digit strings.
FAKE_CHANNEL_A = "111111111111111111"
FAKE_CHANNEL_B = "222222222222222222"


def _load():
    """By path, with paramiko stubbed — the guard never touches it."""
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec = importlib.util.spec_from_file_location("_deploy_restart_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load()


@pytest.fixture(scope="module")
def real_example(guard):
    text, source = guard.load_tracked_example()
    guard.check_example_control(text, source)
    return text


# -- the harness read the real file, not an empty string --------------------

def test_the_example_the_harness_reads_is_the_real_one(guard, real_example):
    """The positive control. Every case below compares against this text, so an
    empty or stub `.example` would make all of them pass for nothing."""
    assert len(real_example.split("\n")) >= guard.EXAMPLE_MIN_LINES
    for anchor in guard.EXAMPLE_ANCHORS:
        hits = [ln for ln in real_example.split("\n") if anchor in ln]
        assert len(hits) == 1, f"anchor {anchor!r} on {len(hits)} lines"


def test_the_control_rejects_an_empty_string(guard):
    """The control's own control: it must be able to fail."""
    with pytest.raises(SystemExit):
        guard.check_example_control("", "fixture")
    with pytest.raises(SystemExit):
        guard.check_example_control("#!/bin/bash\n", "fixture")


def test_the_loader_prefers_the_tracked_blob_over_the_working_tree(guard):
    """A checkout behind origin/main carries a stale `.example`; comparing
    against it fails on lines that are not drift."""
    _, source = guard.load_tracked_example()
    assert source.startswith("git "), source


# -- the four required cases ------------------------------------------------

_ASSIGN = re.compile(r"^(\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=)(.*)$")


def _sole_line(lines, matches):
    """The one line `matches` picks out, so a mutation cannot land on another.

    `next(...)` takes the first and says nothing about the rest, which is how a
    mutation ends up editing a line other than the one the test names.
    """
    hits = [i for i, ln in enumerate(lines) if matches(ln)]
    assert len(hits) == 1, (
        f"the mutation target must be unique; {len(hits)} lines match "
        f"(1-based: {[i + 1 for i in hits]})"
    )
    return hits[0]


def _fill(example_text, a=FAKE_CHANNEL_A, b=FAKE_CHANNEL_B):
    """The `.example` with only its two placeholders filled — i.e. a correct L2.

    Spelled out here rather than imported from the module under test: a fixture
    built by the code it exercises would pass whatever that code happened to do.
    """
    filler = {"CHANNEL_KTP": a, "CHANNEL_EXTERNAL": b}
    out = []
    for ln in example_text.split("\n"):
        m = _ASSIGN.match(ln)
        key = m.group(2) if m else None
        out.append(f'{key}="{filler[key]}"' if key in filler else ln)
    return "\n".join(out)


def test_differing_only_on_allowlisted_keys_passes(guard, real_example):
    assert guard.example_guard(_fill(real_example), real_example) == []


def test_identical_to_the_example_fails_because_the_placeholders_are_unfilled(guard, real_example):
    """A file byte-identical to the `.example` is not a deployable canonical:
    shipping it blanks both channel IDs and the 03:00 notification stops while
    the restart still prints green."""
    findings = guard.example_guard(real_example, real_example)
    assert [f.kind for f in findings] == ["unfilled", "unfilled"]
    assert "CHANNEL_KTP" in findings[0].detail
    assert "CHANNEL_EXTERNAL" in findings[1].detail


def test_identical_after_filling_is_the_passing_case(guard, real_example):
    """The `identical` half of the brief, stated the way the invariant means it:
    identical once the two placeholders carry values."""
    filled = _fill(real_example)
    assert guard.example_guard(filled, real_example) == []
    # ...and the same text compared against itself is still clean.
    assert guard.example_guard(filled, filled) == []


def test_a_non_allowlisted_line_fails_and_is_named(guard, real_example):
    lines = _fill(real_example).split("\n")
    target = _sole_line(lines, lambda ln: ln.strip().startswith("EXPECTED_RUNNING="))
    lines[target] = "EXPECTED_RUNNING=99"
    findings = guard.example_guard("\n".join(lines), real_example)
    assert findings, "a changed non-allowlisted assignment must fail"
    blob = "\n".join(f.detail for f in findings)
    assert f"canonical:{target + 1}" in blob
    assert "EXPECTED_RUNNING" in blob


def test_the_three_line_comment_case_fails(guard, real_example):
    """Today's actual drift: the `.example` carries a comment block the real
    canonical lacks. A guard that only looked at assignments would miss it."""
    lines = _fill(real_example).split("\n")
    start = _sole_line(
        lines, lambda ln: ln.startswith("# A quiet sweep is still not proof of health"))
    stripped = lines[:start] + lines[start + 3:]
    findings = guard.example_guard("\n".join(stripped), real_example)
    assert findings, "a comment block present only in the .example must fail"
    blob = "\n".join(f.detail for f in findings)
    assert "quiet sweep is still not proof of health" in blob
    assert f"example:{start + 1}" in blob


def test_a_line_only_in_the_canonical_fails(guard, real_example):
    """Drift runs both ways; an addition the `.example` never got is drift too."""
    lines = _fill(real_example).split("\n")
    lines.insert(200, "# a line the tracked lineage never received")
    findings = guard.example_guard("\n".join(lines), real_example)
    assert findings
    assert "canonical:201" in "\n".join(f.detail for f in findings)


# -- it never leaks what it protects ----------------------------------------

def test_no_finding_ever_carries_a_canonical_line_body(guard, real_example):
    """The guard's output goes to a terminal and into pasted CI logs. A canonical
    line may be named by number and key; its body must not appear."""
    lines = _fill(real_example).split("\n")
    lines.insert(300, "SOME_LOCAL_SECRET=hunter2-do-not-print-me")
    findings = guard.example_guard("\n".join(lines), real_example)
    blob = "\n".join(f.detail for f in findings)
    assert "hunter2-do-not-print-me" not in blob
    assert "SOME_LOCAL_SECRET" in blob and "canonical:301" in blob


def test_an_allowlisted_value_is_never_printed(guard, real_example):
    lines = _fill(real_example, a="313131313131313131", b="414141414141414141").split("\n")
    lines[0] = "#!/bin/sh"  # force a finding so there is output at all
    findings = guard.example_guard("\n".join(lines), real_example)
    blob = "\n".join(f.detail for f in findings)
    assert "313131313131313131" not in blob
    assert "414141414141414141" not in blob


# -- the allowlist, and the normalisation -----------------------------------

def test_the_allowlist_is_exactly_the_examples_placeholders(guard, real_example):
    """Completeness, re-derived rather than remembered: the `.example` marks its
    fill-me values, and the allowlist must cover those and no more."""
    assert guard.allowlist_gaps(real_example) == []
    marked = {m.group(2) for ln in real_example.split("\n")
              for m in [_ASSIGN.match(ln)]
              if m and guard._PLACEHOLDER.search(m.group(3).strip().strip("\"'"))}
    assert marked == set(guard.HOSTINFO_KEYS)


def test_an_uncovered_placeholder_in_the_example_blocks(guard, real_example):
    """The allowlist must not go stale silently the day L3 gains a third."""
    lines = _fill(real_example).split("\n")
    ex = real_example.split("\n")
    lines.insert(80, 'NEW_HOSTINFO="filled-in-locally"')
    ex.insert(80, 'NEW_HOSTINFO="__PLACEHOLDER__"')
    findings = guard.example_guard("\n".join(lines), "\n".join(ex))
    assert any(f.kind == "allowlist-gap" and "NEW_HOSTINFO" in f.detail for f in findings)


def test_normalisation_is_inert_on_the_real_pair(guard, real_example):
    """The brief's requirement: prove the normalisation masks no real difference.
    It cannot mask what is not there — neither file carries a CR byte or a line
    with trailing whitespace, so normalise() only splits lines."""
    assert guard.normalisation_is_inert(real_example)
    if not CANONICAL.exists():
        pytest.skip("canonical is gitignored; absent in a CI checkout")
    assert guard.normalisation_is_inert(CANONICAL.read_text(encoding="utf-8"))


def test_normalisation_absorbs_line_endings_and_trailing_space(guard, real_example):
    filled = _fill(real_example)
    crlf = filled.replace("\n", "\r\n")
    assert guard.example_guard(crlf, real_example) == []
    spaced = "\n".join(ln + "   " for ln in filled.split("\n"))
    assert guard.example_guard(spaced, real_example) == []


def test_normalisation_does_not_hide_a_real_edit(guard, real_example):
    """The control for the two cases above: normalising still fails on a change
    that is not whitespace, so the tolerance is not just 'compare nothing'."""
    filled = _fill(real_example).replace("\n", "\r\n").replace("EXPECTED_RUNNING=", "EXPECTED_X=", 1)
    assert guard.example_guard(filled, real_example)


# -- the gate refuses, and the override is loud -----------------------------

def test_the_gate_refuses_on_a_finding(guard, real_example, monkeypatch, capsys):
    monkeypatch.setattr(guard, "load_tracked_example", lambda *a, **k: (real_example, "fixture"))
    broken = _fill(real_example).replace("#!/bin/bash", "#!/bin/sh", 1)
    with pytest.raises(SystemExit) as e:
        guard.gate_on_example(broken, None)
    assert "Refusing to deploy" in str(e.value)
    assert "FAIL" in capsys.readouterr().out


def test_the_gate_passes_a_correct_canonical(guard, real_example, monkeypatch, capsys):
    monkeypatch.setattr(guard, "load_tracked_example", lambda *a, **k: (real_example, "fixture"))
    guard.gate_on_example(_fill(real_example), None)
    assert "PASS" in capsys.readouterr().out


def test_the_override_ships_but_says_so(guard, real_example, monkeypatch, capsys):
    monkeypatch.setattr(guard, "load_tracked_example", lambda *a, **k: (real_example, "fixture"))
    broken = _fill(real_example).replace("#!/bin/bash", "#!/bin/sh", 1)
    guard.gate_on_example(broken, "example deliberately ahead, see PR #123")
    out = capsys.readouterr().out
    assert "EXAMPLE GUARD OVERRIDDEN" in out
    assert "example deliberately ahead, see PR #123" in out


def test_an_empty_override_reason_is_rejected(guard):
    """Tested through the function, never by running the deploy script: a suite
    that shells out to it would put a fleet-writing tool in CI's hands."""
    with pytest.raises(SystemExit):
        guard.validated_override("   ")
    assert guard.validated_override(None) is None
    assert guard.validated_override("a real reason") == "a real reason"


# -- and the verdict on today's real files ----------------------------------

def test_the_real_canonical_is_currently_drifted(guard, real_example):
    """⚠️ EXPECTED TO FAIL THE GUARD, and that is the finding, not a broken test.

    The tracked `.example` carries a three-line comment about the socket-map
    sweep that the real canonical lacks — and since the canonical's md5 equals
    the fleet's, all 24 hosts lack it too. Reconciling it (and whether the fleet
    should get it) is an operator decision, so this asserts the drift rather
    than removing it.

    When it IS reconciled this test fails, which is the correct way to be told.
    """
    if not CANONICAL.exists():
        pytest.skip("canonical is gitignored; absent in a CI checkout")
    findings = guard.example_guard(CANONICAL.read_text(encoding="utf-8"), real_example)
    kinds = [f.kind for f in findings]
    assert kinds == ["insert"], f"unexpected drift shape: {kinds}"
    assert "quiet sweep is still not proof of health" in findings[0].detail
