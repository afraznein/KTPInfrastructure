"""Filename-grammar regression tests for scripts/ktp-organize-hltv-demos.sh.

The organizer files a demo by matching its name against an ordered if/elif chain.
Every failure this script has had was a grammar failure, and all of them were
quiet: an unmatched name is logged as a skip and the job still exits 0.

  * The single-host branch accepted `1.3-<digits>` and `1.3-<letters>` but not
    `1.3-<alphanumeric>`, so a queue ID typed as `12man` fell through -- while the
    double-host branch already allowed the mixed class.
  * When the renamer started appending a second host segment to every name, 112
    match demos went unfiled for five days inside ~450 lines of expected `auto*`
    skips.

The second one also fixes which capture group the host comes from. The trailing
segment is the WRONG value -- filing on it would put every server's demos under one
host -- so the double-host branch must take group 5, not group 6.

These tests read the branch patterns out of the tracked script and replay them
through bash, so they cannot drift from it: edit the chain and the expectations
here move with it or fail. Nothing here asserts on file size.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "ktp-organize-hltv-demos.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt", reason="needs bash"
)

# `[[ "$demo" =~ <pattern> ]]` -- in source order, which is match order.
_BRANCH = re.compile(r'\[\[\s*"\$demo"\s*=~\s*(\^\S+\$)\s*\]\]')


def _branches() -> list[str]:
    assert SCRIPT.is_file(), f"organizer not found at {SCRIPT}"
    pats = _BRANCH.findall(SCRIPT.read_text(encoding="utf-8"))
    # A path-relative loader that finds nothing reports every name as unmatched,
    # which reads exactly like a grammar that rejects everything.
    assert len(pats) >= 5, f"only {len(pats)} branch pattern(s) extracted -- parser is broken"
    return pats


def _classify(name: str) -> tuple[int | None, list[str]]:
    """Return (index of the first matching branch, its capture groups)."""
    pats = _branches()
    script = ['demo="$1"', "shift"]
    for i, p in enumerate(pats):
        kw = "if" if i == 0 else "elif"
        script.append(f'{kw} [[ "$demo" =~ {p} ]]; then')
        script.append(f'    echo "BRANCH {i}"')
        script.append('    printf "%s\\n" "${BASH_REMATCH[@]}"')
    script.append("else")
    script.append('    echo "BRANCH none"')
    script.append("fi")
    out = subprocess.run(
        ["bash", "-c", "\n".join(script), "_", name],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    lines = out.stdout.splitlines()
    head = lines[0].split()[1]
    return (None if head == "none" else int(head)), lines[1:]


DOUBLE_HOST = "12man_1.3-6404-NY1-ATL1_h2-2608062130-dod_armory_b6.dem"
ALNUM_QUEUE_ID = "12man_1.3-12man-ATL1_h1-2608032221-dod_armory_b6.dem"


def test_every_known_shape_matches_some_branch():
    names = [
        "ktp_1772417515-ATL1_h1-2603012111-dod_anzio.dem",
        "12man_1.3-6381-ATL1_h1-2608032221-dod_armory_b6.dem",
        ALNUM_QUEUE_ID,
        DOUBLE_HOST,
        "ktp_KTP-1768359925-dod_anjou_a4-KTP_Dallas_3-2601132205-dod_anjou_a4.dem",
    ]
    unmatched = [n for n in names if _classify(n)[0] is None]
    assert not unmatched, f"grammar rejects known-good names: {unmatched}"


def test_alphanumeric_queue_id_is_accepted():
    """`12man` typed into the Queue ID field is a bad id, but it is a real one."""
    idx, groups = _classify(ALNUM_QUEUE_ID)
    assert idx is not None
    assert groups[1] == "12man", f"match type mis-parsed: {groups[:3]}"
    assert "ATL1" in groups, f"host ATL1 not captured: {groups}"


def test_double_host_captures_both_hosts_in_the_expected_groups():
    """Group 5 is the host from the match ID; group 6 is the renamer's wrong guess."""
    idx, groups = _classify(DOUBLE_HOST)
    assert idx is not None, "double-host names are unmatched -- demos will go unfiled"
    # groups[0] is the whole match; BASH_REMATCH[n] is groups[n].
    assert groups[5] == "NY1", f"expected match-ID host NY1 in group 5, got {groups[5]!r}"
    assert groups[6] == "ATL1", f"expected trailing host ATL1 in group 6, got {groups[6]!r}"


def test_double_host_branch_files_under_group_5():
    """Capturing both hosts is not enough -- the branch must USE the match-ID one.

    Filing on the trailing segment would put every server's demos under one host,
    and every name would still match, so no grammar assertion can catch it.
    """
    body = SCRIPT.read_text(encoding="utf-8")
    branch = body[body.index("-([A-Z]+[0-9]+)-([A-Z]+[0-9]+)"):]
    assign = re.search(r'hostname="\$\{BASH_REMATCH\[(\d)\]\}"', branch)
    assert assign, "double-host branch assigns no hostname"
    assert assign.group(1) == "5", (
        f"double-host branch files under group {assign.group(1)}, not the match-ID host (5)"
    )


def test_auto_recordings_match_nothing():
    """HLTV's continuous recordings are supposed to fall through to the skip path."""
    for name in ("auto-20260806-2130-dod_anzio.dem", "auto0001.dem"):
        assert _classify(name)[0] is None, f"{name} should not be filed as a match demo"


def test_the_skip_path_separates_auto_from_genuinely_unrecognized():
    """A real unfiled demo must be named in the log; ~450 auto skips must not bury it."""
    body = SCRIPT.read_text(encoding="utf-8")
    assert "auto*)" in body, "no auto* case in the skip triage"
    assert "UNRECOGNIZED" in body, "unrecognized demos are not called out"
    assert "WARNING" in body, "an unfiled match demo does not raise a warning"
