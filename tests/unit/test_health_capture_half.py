"""ktp-data-server-health.sh: one lost match-half is a state of its own.

The 24h `capture-loss:<event_type>` leg is a cumulative counter under a
windowed headline. On 2026-10-07 a match-half had 100% of eleven event types
rejected and that headline stayed under its 5% warn, because a dead half
divided by a day of healthy traffic is a rounding error. The block under test
is the second leg: score every (half, event_type) in the window, report the
worst, and separately count halves whose manifest arrived and whose health rows
never did.

Three things this file exists to keep true, all of which have already cost this
estate an incident:

  * a single lost half must survive being averaged against a healthy day,
  * the shipped threshold must be reachable. An alert threshold above
    everything ever observed is an alert that cannot fire, and
  * a refusal must say why it refused. Until migration 044 none did: every
    rejection site computed the reason as its dispatch status string, tested it
    to decide the marker was refused, then threw it away, so a lost half was
    pageable and not diagnosable. The third reducer is the assertion that the
    fix is still in force.

The reducers and the latch are extracted from the shipped script by marker, so
renaming or deleting either fails this file rather than testing a copy that no
longer ships. No database is involved: the reducers take the rows mysql would
have printed, on stdin.
"""
import os
import pathlib
import re
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
# CI runs plain bash; on a Windows workstation "bash" resolves to WSL's, which
# cannot see these paths -- point KTP_TEST_BASH at Git Bash there.
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")


def block(name):
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    text = SCRIPT.read_text(encoding="utf-8")
    assert begin in text and end in text, "%s markers are gone from the shipped script" % name
    return text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def shipped(var):
    """The default the script ships for `var`, as an int."""
    m = re.search(r'^%s="\$\{%s:-(-?\d+)\}"$' % (var, var), block("ktp-capture-half"), re.M)
    assert m, "%s is no longer a plain numeric default in the shipped block" % var
    return int(m.group(1))


def bash(tmp_path, body, name="probe.sh"):
    # From a file, not `bash -c`: msys2 re-parses a multi-line -c argument on
    # Windows and the failure looks like a bug in the script under test.
    p = tmp_path / name
    p.write_text(body, encoding="utf-8", newline="\n")
    r = subprocess.run([BASH, p.as_posix()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def run(tmp_path, func, rows, marker="ktp-capture-half", **env):
    exports = "".join("%s=%s\n" % kv for kv in env.items())
    body = "%s\n%s\n%s <<'ROWS'\n%s\nROWS\n" % (block(marker), exports, func, rows)
    return bash(tmp_path, body)


def worst(tmp_path, rows, **env):
    """Feed mysql-shaped rows through capture_half_worst; return the one line
    it prints as (pct, crossing, scored, half_key, event_type, ...ints), or
    None when nothing cleared the floor."""
    out = run(tmp_path, "capture_half_worst", rows, **env).strip()
    if out == "":
        return None
    f = out.split("\t")
    assert len(f) == 10, f
    return (int(f[0]), int(f[1]), int(f[2]), f[3], f[4]) + tuple(int(x) for x in f[5:])


def pending(tmp_path, rows, **env):
    out = run(tmp_path, "capture_half_unreconciled", rows, **env).rstrip("\n")
    count, named = out.split("\t")
    return int(count), named


def reasonless(tmp_path, rows, **env):
    """Feed rejecting (half, event_type) rows through capture_half_reasonless;
    return (reasonless, rejecting, named, worst_reason)."""
    out = run(tmp_path, "capture_half_reasonless", rows, **env).rstrip("\n")
    f = out.split("\t")
    assert len(f) == 4, f
    return int(f[0]), int(f[1]), f[2], f[3]


# A rejection row is half_key, event_type, rejected, reasons -- the last field
# as mysql -N -B prints it, which is the four characters NULL for a NULL.
def rej(key, etype, rejected, reasons="NULL"):
    return "\t".join(str(x) for x in (key, etype, rejected, reasons))


# A half key is server/match/half, and a row is
# key, event_type, emitted, received, accepted, rejected, gaps.
def row(key, etype, emitted, received, accepted, rejected, gaps=0):
    return "\t".join(str(x) for x in (key, etype, emitted, received, accepted, rejected, gaps))


HEALTHY_FRAG = [row("4/m%03d/1" % i, "frag", 600, 600, 599, 1, 1) for i in range(40)]
DEAD_HALF = row("4/m999/2", "frag", 600, 600, 0, 600, 0)


# ---------------------------------------------------------------- the defect

def test_one_lost_half_is_not_diluted_by_a_healthy_day(tmp_path):
    """The whole reason this leg exists. Same rows, both reducers: the 24h
    average reads 2% and says nothing, the per-half leg reads 100%."""
    rows = "\n".join(HEALTHY_FRAG + [DEAD_HALF])
    got = worst(tmp_path, rows)
    assert got[0] == 100 and got[3] == "4/m999/2"
    assert got[1] == 1 and got[2] == 41  # one half-stream crossing, 41 scored

    # The sibling's own reducer, on the same events aggregated its way.
    received = 600 * 41
    rejected = 1 * 40 + 600
    sib = bash(tmp_path, "%s\ncapture_loss_rows <<'ROWS'\nfrag\t%d\t%d\nROWS\n"
               % (block("ktp-capture-loss"), received, rejected), "sibling.sh")
    assert int(sib.split("\t")[1]) == 3   # 2.6% -> 3, under its 5% warn
    assert 3 < shipped("CAPTURE_HALF_LOSS_WARN_PCT") <= 100


def test_the_shipped_threshold_can_actually_fire(tmp_path):
    """An alert threshold above everything ever observed is an alert that
    cannot fire. The worst thing observed here is a 100%-lost half."""
    warn, clear = shipped("CAPTURE_HALF_LOSS_WARN_PCT"), shipped("CAPTURE_HALF_LOSS_CLEAR_PCT")
    assert 0 < clear < warn <= 100
    assert worst(tmp_path, DEAD_HALF)[0] >= warn


def test_dilution_inside_a_half_is_not_recommitted(tmp_path):
    """Scoring per half instead of per (half, event_type) would hide a dead
    frag stream behind position, which outnumbers it about twenty to one."""
    rows = "\n".join([row("4/m1/1", "frag", 600, 600, 0, 600),
                      row("4/m1/1", "position", 12000, 12000, 12000, 0)])
    assert worst(tmp_path, rows)[:5] == (100, 1, 2, "4/m1/1", "frag")


# ------------------------------------------- the shape a ratio cannot see

def test_a_half_that_arrived_as_nothing_scores_100_not_nothing(tmp_path):
    """Nothing reached the daemon, so rejected/received is 0/0. Scoring against
    the producer's own `emitted` is what makes this visible at all."""
    assert worst(tmp_path, row("4/m2/1", "frag", 5000, 0, 0, 0, 5000))[:5] == \
        (100, 1, 1, "4/m2/1", "frag")

    # And the proof that the sibling is blind to it: received 0 is under any floor.
    sib = bash(tmp_path, "%s\ncapture_loss_rows <<'ROWS'\nfrag\t0\t0\nROWS\n"
               % block("ktp-capture-loss"), "sibling_blind.sh")
    assert sib == ""


def test_a_half_with_no_health_row_at_all_is_counted_separately(tmp_path):
    """A missing row is not a 100% rate, so the ratio leg cannot see it."""
    assert pending(tmp_path, "4/m7/1\n4/m7/2") == (2, "4/m7/1, 4/m7/2")


def test_no_pending_halves_reads_as_a_measured_zero(tmp_path):
    """Always one line out. A reducer that prints nothing on a clean run is
    indistinguishable from a reducer that failed to run."""
    assert pending(tmp_path, "") == (0, "")


def test_pending_names_at_most_three_but_counts_them_all(tmp_path):
    rows = "\n".join("4/m%d/1" % i for i in range(9))
    count, named = pending(tmp_path, rows)
    assert count == 9 and named == "4/m0/1, 4/m1/1, 4/m2/1"


# ------------------------------------- the refusal that would not say why

# Shapes taken from the live column 2026-10-20, with nothing per-player in them
# -- the daemon strips player ids, quoted payload literals and SteamID-shaped
# tokens before it tallies.
LIFE_REASON = "Life boundary dropped: found 0 event-time match intervals=12"
FRAG_REASON = "frag_context: no matching frag row in the window=1"


def test_a_refusal_that_records_no_reason_is_the_defect_and_fires(tmp_path):
    """The state of the whole estate before migration 044: the half-stream
    refused everything it received and the row says nothing about why. This is
    the assertion that would have caught it, and it has to fire."""
    got = reasonless(tmp_path, rej("4/m999/2", "frag", 600))
    assert got[:3] == (1, 1, "4/m999/2/frag")
    assert got[0] >= shipped("CAPTURE_HALF_REASONLESS_WARN")


def test_the_same_refusal_carrying_a_reason_is_quiet_and_names_the_cause(tmp_path):
    """Post-044, and the half the fix is for: still a refusal, still a loss,
    but a reader can now act on it. The reason reaches the page too -- it is
    worth nothing sitting in a row nobody reads."""
    reasonl, rejecting, named, worst = reasonless(
        tmp_path, rej("4/m999/2", "frag", 600, FRAG_REASON))
    assert (reasonl, rejecting, named) == (0, 1, "")
    assert worst == "4/m999/2/frag " + FRAG_REASON


def test_mysql_null_and_an_empty_field_are_both_reasonless(tmp_path):
    """mysql -N -B prints a NULL as the four characters NULL, so a reducer that
    only tests for emptiness scores a NULL column as a recorded reason -- the
    whole defect, reported clean. Both spellings have to count."""
    rows = "\n".join([rej("4/m1/1", "frag", 10, "NULL"),
                      rej("4/m1/2", "frag", 10, ""),
                      rej("4/m2/1", "life", 10, LIFE_REASON)])
    assert reasonless(tmp_path, rows)[:2] == (2, 3)


def test_no_refusals_at_all_reads_as_a_measured_zero(tmp_path):
    """Always one line out. A reducer that prints nothing on a clean run is
    indistinguishable from a reducer that never ran."""
    assert reasonless(tmp_path, "") == (0, 0, "", "")


def test_a_stream_that_refused_nothing_is_not_a_rejecting_stream(tmp_path):
    """A reason is only owed where something was refused. A clean stream with
    an empty column must not page -- that is every healthy row in the table."""
    rows = "\n".join([rej("4/m1/1", "frag", 0), rej("4/m1/1", "position", 0)])
    assert reasonless(tmp_path, rows) == (0, 0, "", "")


def test_reasonless_names_at_most_three_but_counts_them_all(tmp_path):
    rows = "\n".join(rej("4/m%d/1" % i, "frag", 10) for i in range(9))
    count, rejecting, named, _ = reasonless(tmp_path, rows)
    assert (count, rejecting) == (9, 9)
    assert named == "4/m0/1/frag, 4/m1/1/frag, 4/m2/1/frag"


def test_the_named_cause_is_the_one_behind_the_most_refused_events(tmp_path):
    """One line of detail, so it has to describe the most damage rather than
    whichever row mysql happened to return first."""
    rows = "\n".join([rej("4/small/1", "frag", 3, FRAG_REASON),
                      rej("4/big/1", "life", 48, LIFE_REASON),
                      rej("4/mid/1", "frag", 9, FRAG_REASON)])
    assert reasonless(tmp_path, rows)[3] == "4/big/1/life " + LIFE_REASON


def test_a_reasonless_stream_still_names_a_cause_from_its_siblings(tmp_path):
    """A window can hold both states at once. Counting the one that says
    nothing must not suppress the cause the others do record."""
    rows = "\n".join([rej("4/m1/1", "frag", 600),
                      rej("4/m1/1", "life", 48, LIFE_REASON)])
    count, rejecting, named, worst = reasonless(tmp_path, rows)
    assert (count, rejecting, named) == (1, 2, "4/m1/1/frag")
    assert worst == "4/m1/1/life " + LIFE_REASON


def test_malformed_input_is_dropped_rather_than_counted(tmp_path):
    assert reasonless(tmp_path, "\nnot a row\n4/m5/1\tfrag") == (0, 0, "", "")


def test_the_shipped_reasonless_threshold_can_actually_fire(tmp_path):
    """Measured read-only 2026-10-20: of 623 rejecting half-streams written
    before the 10-13 daemon swap, 623 record no reason; of 49 written after,
    none. So warn 1 is not merely reachable, it is where the data sits."""
    warn = shipped("CAPTURE_HALF_REASONLESS_WARN")
    assert warn == 1
    assert reasonless(tmp_path, rej("4/m999/2", "frag", 600))[0] >= warn


# ------------------------------------------------------------- staying quiet

def test_a_healthy_day_fires_nothing(tmp_path):
    """0.1-0.2% transit loss on every stream, which is the measured normal."""
    rows = "\n".join(HEALTHY_FRAG + [row("4/m%03d/1" % i, "position", 12000, 11988, 11988, 0, 12)
                                     for i in range(40)])
    got = worst(tmp_path, rows)
    assert got[0] == 0 and got[1] == 0 and got[2] == 80


def test_rows_under_the_floor_are_dropped_not_scored(tmp_path):
    """A sparse stream losing everything is 100% of very little. 199 emitted
    must not page; the next event over the floor must."""
    assert worst(tmp_path, row("4/m3/1", "assist", 199, 0, 0, 0)) is None
    assert worst(tmp_path, row("4/m3/1", "assist", 200, 0, 0, 0))[0] == 100


def test_floor_is_tunable(tmp_path):
    assert worst(tmp_path, row("4/m4/1", "assist", 150, 0, 0, 0),
                 CAPTURE_HALF_MIN_EMITTED=100)[0] == 100


def test_empty_and_malformed_input_produce_nothing(tmp_path):
    assert worst(tmp_path, "") is None
    assert worst(tmp_path, "\nnot a row\n4/m5/1\tfrag\t5000") is None


def test_zero_emitted_is_dropped_rather_than_dividing_by_zero(tmp_path):
    assert worst(tmp_path, row("4/m6/1", "frag", 0, 0, 0, 0)) is None


def test_accepted_above_emitted_clamps_to_zero(tmp_path):
    """Resends and a late flush can put accepted ahead of the producer's count.
    That is not negative loss."""
    assert worst(tmp_path, row("4/m8/1", "frag", 600, 610, 610, 0))[0] == 0


def test_ties_break_on_events_lost(tmp_path):
    """Two halves at the same percentage: name the one that lost more events."""
    rows = "\n".join([row("4/small/1", "frag", 300, 0, 0, 0),
                      row("4/big/1", "frag", 9000, 0, 0, 0),
                      row("4/mid/1", "frag", 1000, 0, 0, 0)])
    assert worst(tmp_path, rows)[3] == "4/big/1"


# ------------------------------------------------------------------- latching

def replay(tmp_path, key, series, warn_var, clear_var):
    """Run a per-run value series through the real latch, carrying the
    previous-down set between runs the way the hourly cron does."""
    prev = tmp_path / "prev.list"
    prev.write_text("", encoding="utf-8")
    src = block("ktp-alert-latch") + block("ktp-capture-half")
    verdicts = []
    for i, val in enumerate(series):
        body = ('%s\nPREV_LIST=%s\nif latched %s %d "$%s" "$%s"; then echo YES; else echo NO; fi\n'
                % (src, prev.as_posix(), key, val, warn_var, clear_var))
        fired = bash(tmp_path, body, "latch%d.sh" % i).strip() == "YES"
        verdicts.append(fired)
        prev.write_text("%s\n" % key if fired else "", encoding="utf-8")
    return verdicts


def test_a_lost_half_pages_once_and_releases_when_the_window_rolls_past_it(tmp_path):
    """100 on the run that sees the half, held while it stays in the window,
    released when the trailing window no longer contains it. The key is
    constant, so that release is an honest "no bad half in the window" rather
    than a recovery announced for a half that aged out."""
    assert replay(tmp_path, "capture-half-loss", [0, 100, 100, 100, 0],
                  "CAPTURE_HALF_LOSS_WARN_PCT", "CAPTURE_HALF_LOSS_CLEAR_PCT") == \
        [False, True, True, True, False]


def test_a_single_unreconciled_half_pages_and_zero_clears(tmp_path):
    assert replay(tmp_path, "capture-half-unreconciled", [0, 1, 2, 0],
                  "CAPTURE_HALF_UNRECONCILED_WARN", "CAPTURE_HALF_UNRECONCILED_WARN") == \
        [False, True, True, False]


def test_one_reasonless_refusal_pages_and_zero_clears(tmp_path):
    """Pre-044 rows stay in the table, so the trailing window is what makes
    this release rather than a backfill. Zero has to clear it."""
    assert replay(tmp_path, "capture-half-reasonless", [0, 1, 3, 0],
                  "CAPTURE_HALF_REASONLESS_WARN", "CAPTURE_HALF_REASONLESS_WARN") == \
        [False, True, True, False]
