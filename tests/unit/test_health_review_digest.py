"""ktp-data-server-health.sh: a review digest that owed a post and never made one.

The AC review digest is the only thing that routes the review backlog to a
person. Its cadence marker advances only on a delivered post and is rolled back
on every other outcome, so one marker value covers both "nothing to report" and
"broken for weeks" -- and the service's own failure line, which says in as many
words that nobody was told, was read by nothing on a schedule.

The reducer and the latch are extracted from the shipped script by marker, so
renaming or deleting either fails this file rather than testing a copy that no
longer ships. No journal and no database are involved: the reducer takes the
lines journalctl would have printed, on stdin, and both ages as arguments.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
# CI runs plain bash; on a Windows workstation "bash" resolves to WSL's, which
# cannot see these paths -- point KTP_TEST_BASH at Git Bash there.
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")

POSTED = "posted unreviewed-review digest; next in 7d — posted — gated session(s)"
QUIET = "unreviewed digest stayed quiet — nothing to report"
FAILED = "unreviewed digest did NOT post and nobody was told — relay refused"

OK_FLOOR = "72"      # journal reaches comfortably past the shipped window
NOT_DUE = "115"      # a delivered post, inside the period
OVERDUE = "400"      # the marker has not advanced across the period


def block(name):
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    text = SCRIPT.read_text(encoding="utf-8")
    assert begin in text and end in text, "%s markers are gone from the shipped script" % name
    return text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def bash(tmp_path, body, name="probe.sh"):
    # From a file, not `bash -c`: msys2 re-parses a multi-line -c argument on
    # Windows and the failure looks like a bug in the script under test.
    p = tmp_path / name
    p.write_text(body, encoding="utf-8", newline="\n")
    r = subprocess.run([BASH, p.as_posix()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def reduce(tmp_path, lines, marker_age=NOT_DUE, floor_age=OK_FLOOR, **env):
    """Feed journal lines through ac_digest_rows; return {key: (value, note)}."""
    # Single-quoted: a literal override carries spaces, and an unquoted
    # assignment splits into a command that silently runs instead.
    exports = "".join("%s='%s'\n" % kv for kv in env.items())
    body = "%s\n%s\nac_digest_rows %s %s <<'LINES'\n%s\nLINES\n" % (
        block("ktp-ac-digest"), exports, marker_age, floor_age, "\n".join(lines))
    out = {}
    for line in bash(tmp_path, body).splitlines():
        key, value, note = line.split("\t")
        out[key] = (int(value), note)
    return out


def test_a_delivered_digest_inside_its_period_is_clean(tmp_path):
    assert reduce(tmp_path, [POSTED]) == {}


def test_a_failed_post_is_reported_and_counted(tmp_path):
    rows = reduce(tmp_path, [FAILED, POSTED, FAILED])
    assert rows["ac-review-digest:failed"][0] == 2
    assert "nobody was told" not in rows["ac-review-digest:failed"][1]  # the note is ours, not the log's
    assert "ac-review-digest:loop-silent" not in rows


def test_a_quiet_backlog_is_quiet_and_not_a_fault(tmp_path):
    """The marker rolls back on an empty backlog, so it sits overdue forever.
    That is the digest working, and the only thing separating it from a broken
    one is this log line."""
    assert reduce(tmp_path, [QUIET, QUIET], marker_age=OVERDUE) == {}


def test_overdue_with_no_outcome_at_all_is_the_loop_not_ticking(tmp_path):
    rows = reduce(tmp_path, ["some unrelated line"], marker_age=OVERDUE)
    assert "ac-review-digest:loop-silent" in rows
    assert "ac-review-digest:failed" not in rows


def test_an_overdue_marker_with_a_failure_reports_the_failure_not_silence(tmp_path):
    rows = reduce(tmp_path, [FAILED], marker_age=OVERDUE)
    assert "ac-review-digest:failed" in rows
    assert "ac-review-digest:loop-silent" not in rows


def test_no_lines_at_all_inside_the_period_says_nothing(tmp_path):
    """Between digests the service logs no outcome: the due test returns early
    before any log line. Silence there is normal and must not page."""
    assert reduce(tmp_path, []) == {}


def test_an_unreadable_marker_is_unmeasurable_not_clean(tmp_path):
    for bad in ("", "unknown", "-3", "not-a-number"):
        rows = reduce(tmp_path, [FAILED], marker_age=bad or '""')
        assert "ac-review-digest=unmeasurable" in rows, bad
        assert "ac-review-digest:failed" not in rows, bad


def test_a_journal_shorter_than_the_window_is_unmeasurable_not_clean(tmp_path):
    """That journal is size-bounded, not time-bounded, so the floor moves on its
    own. A window it cannot cover would score a clean zero out of absent lines."""
    rows = reduce(tmp_path, [], floor_age="4")
    assert "ac-review-digest=unmeasurable" in rows
    rows = reduce(tmp_path, [], floor_age="unknown")
    assert "ac-review-digest=unmeasurable" in rows


def test_the_window_is_tunable_and_the_floor_test_follows_it(tmp_path):
    assert reduce(tmp_path, [], floor_age="40", AC_DIGEST_WINDOW_HOURS=48) != {}
    assert reduce(tmp_path, [], floor_age="40", AC_DIGEST_WINDOW_HOURS=12) == {}


def test_the_literals_are_the_contract_with_the_api(tmp_path):
    """A reword on the API side makes this blind in the quiet direction, so the
    shipped defaults are pinned here rather than left to a grep."""
    shipped = block("ktp-ac-digest")
    for literal in ("posted unreviewed-review digest",
                    "unreviewed digest stayed quiet",
                    "did NOT post and nobody was told"):
        assert literal in shipped, literal
    # And a renamed literal must stop matching, or the pin above proves nothing.
    rows = reduce(tmp_path, [FAILED], AC_DIGEST_FAILED_LITERAL="a different wording")
    assert "ac-review-digest:failed" not in rows


def replay(tmp_path, series):
    """Run a per-run failure count through the real latch, carrying the
    previous-down set between runs the way the scheduled run does."""
    prev = tmp_path / "prev.list"
    prev.write_text("", encoding="utf-8")
    src = block("ktp-alert-latch") + block("ktp-ac-digest")
    verdicts = []
    for i, failures in enumerate(series):
        body = ("%s\nPREV_LIST=%s\nif latched ac-review-digest:failed %d "
                "\"$AC_DIGEST_FAIL_WARN\" \"$AC_DIGEST_FAIL_CLEAR\"; then echo YES; else echo NO; fi\n"
                % (src, prev.as_posix(), failures))
        fired = bash(tmp_path, body, "probe%d.sh" % i).strip() == "YES"
        verdicts.append(fired)
        prev.write_text("ac-review-digest:failed\n" if fired else "", encoding="utf-8")
    return verdicts


def test_one_unrouted_week_pages_and_a_recovery_clears(tmp_path):
    assert replay(tmp_path, [0, 1, 2, 1, 0, 0]) == [False, True, True, True, False, False]


def test_the_clear_floor_still_releases(tmp_path):
    """CLEAR at 0 would make the mid-band test true for every count and the item
    would never clear again. This is the regression that pins it off the floor."""
    assert replay(tmp_path, [1, 0]) == [True, False]
