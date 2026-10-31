"""Every `CRITICAL_TIMERS` entry has a row in ALERT_COVERAGE.md's timer table.

That runbook's own rule is that adding a timer means adding a row in the same
change. The rule was a paragraph, and it was broken twice: four live timers sat
unlisted until 2026-10-12, and then `ktp-install-freshness.timer` (10-13) and
`ktp-map-coefficients.timer` (10-14) joined the list with a reason written into
the array and no row in the table -- each in a change that cited the runbook.

The invariant is ONE-WAY. A row marked **no** for a timer outside
`CRITICAL_TIMERS` is the table doing its job (five of them are deliberate), so
the reverse containment is not asserted and must not be: asserting it would
delete exactly the rows that record an uncovered timer.

Both sides are parsed out of the shipped artifacts, so renaming the array or
retitling the table fails here rather than testing a copy that no longer ships.

Mutation-checked, and one result is worth stating because it reads like a gap:
DELETING an array entry leaves this file green, deliberately. Containment is
one-way, so a shorter list cannot violate it -- that direction belongs to the
per-timer membership tests (`test_health_map_coefficients_timer.py` and the
rest), which exist because deleting an entry once passed the whole health suite
silently.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ktp-data-server-health.sh"
RUNBOOK = REPO / "docs" / "runbooks" / "ALERT_COVERAGE.md"

# Verified absent from both artifacts by this file's own control test -- the
# namespace that matters is these two files, not the repo.
NONSENSE = "qqz_nonexistent_token_7731.timer"


def critical_timers() -> list[str]:
    """The array's entries, from the shipped script, comments dropped.

    The array is heavily commented and its comments name units that are
    deliberately NOT entries (`ktp-monday-reminder.timer`), so a substring
    search over the raw block would pass on prose alone.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"(?ms)^CRITICAL_TIMERS=\(\n(.*?)^\)", text)
    assert m, "CRITICAL_TIMERS array is gone from the shipped script"
    out = []
    for ln in m.group(1).split("\n"):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def _timer_table_block() -> list[str]:
    """The timer table's data rows, located by its header row.

    Anchored on a line START plus the exact header cells, and asserted to match
    once: prose in this file quotes `CRITICAL_TIMERS` constantly, and a guard
    that locates a table by a word in it would latch onto a sentence about the
    table. The block ends at the first line that is not a table row.
    """
    lines = RUNBOOK.read_text(encoding="utf-8").split("\n")
    heads = [i for i, l in enumerate(lines) if l.startswith("| Timer | In `CRITICAL_TIMERS` |")]
    assert len(heads) == 1, (
        "expected exactly one timer-table header in %s, found %d -- a second "
        "match means the table moved or a sentence is being read as one"
        % (RUNBOOK.name, len(heads))
    )
    i = heads[0]
    rows = []
    for ln in lines[i + 2:]:          # +2 skips the header and its |---| rule
        if not ln.startswith("|"):
            break
        rows.append(ln)
    return rows


def table_timers() -> set[str]:
    """Timer unit names in the table's FIRST column only.

    First column only, because the "if it silently stops" cell names other
    units freely -- the `ktp-identity-reconcile` row talks about its service and
    the `support-poller` row about the hourly sweep.
    """
    names: set[str] = set()
    for row in _timer_table_block():
        first = row.split("|")[1]
        names.update(re.findall(r"`([a-z0-9@._-]+\.timer)`", first))
        # `ktp-corpus-push.timer` / `-denver` is one row for two units.
        if "-denver" in first:
            names.add("ktp-corpus-push-denver.timer")
    return names


# --------------------------------------------------------------------------
# The invariant
# --------------------------------------------------------------------------

def test_every_critical_timer_has_a_row():
    missing = sorted(set(critical_timers()) - table_timers())
    assert not missing, (
        "in CRITICAL_TIMERS with no row in ALERT_COVERAGE.md's timer table: %s "
        "-- add the row in this change, per that file's own rule" % missing
    )


def test_the_reverse_is_deliberately_not_asserted():
    """A row for a timer outside the list is the table's whole point.

    Keeps the one-way direction explicit, so nobody "fixes" the test above by
    pruning the uncovered rows it does not require.
    """
    extra = table_timers() - set(critical_timers())
    assert extra, (
        "no row describes a timer outside CRITICAL_TIMERS -- either every timer "
        "is now covered (record that above) or the uncovered rows were deleted"
    )


# --------------------------------------------------------------------------
# Controls: each side must be able to fail
# --------------------------------------------------------------------------

def test_both_sides_parse_non_empty():
    """A floor, because set difference over an empty set is empty.

    An unreadable array or a retitled table would otherwise satisfy the
    invariant by having nothing to check.
    """
    entries = critical_timers()
    assert len(entries) >= 10, "only %d CRITICAL_TIMERS entries parsed" % len(entries)
    assert len(table_timers()) >= 10, "the timer table parsed too few rows to mean anything"
    assert len(_timer_table_block()) >= 10


def test_every_entry_looks_like_a_timer_unit():
    for e in critical_timers():
        assert e.endswith(".timer"), "non-timer entry in CRITICAL_TIMERS: %r" % e


def test_no_duplicate_entries():
    e = critical_timers()
    assert len(e) == len(set(e)), "duplicate entries: %r" % [x for x in e if e.count(x) > 1]


def test_the_comment_parse_drops_a_deliberately_unlisted_unit():
    """`ktp-monday-reminder.timer` is named in an array comment and is not an
    entry. If it ever reads as one, the parse is matching prose and the
    invariant above is being satisfied by comments."""
    assert "ktp-monday-reminder.timer" not in critical_timers()


def test_nonsense_control_is_absent_from_both_artifacts():
    """The namespace the check searches is these two files."""
    assert NONSENSE not in SCRIPT.read_text(encoding="utf-8")
    assert NONSENSE not in RUNBOOK.read_text(encoding="utf-8")
    assert NONSENSE not in critical_timers()
    assert NONSENSE not in table_timers()


def test_an_injected_entry_is_detected():
    """The invariant fires on an entry with no row -- proved against an
    injected name rather than by trusting today's agreement, which is exactly
    the state in which a broken comparison looks like a pass."""
    entries = set(critical_timers()) | {NONSENSE}
    assert sorted(entries - table_timers()) == [NONSENSE]


def test_an_injected_row_does_not_fire():
    """The one-way direction, from the other side."""
    assert not set(critical_timers()) - (table_timers() | {NONSENSE})
