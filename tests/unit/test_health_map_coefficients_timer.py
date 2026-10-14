"""ktp-data-server-health.sh: the weekly map-coefficient refit timer is covered.

Unlike the corpus-integrity guard and the hltv-api drift check -- both `cron.d`
jobs, and therefore structurally invisible to CRITICAL_TIMERS -- this one IS a
systemd timer, so the existing `systemctl list-timers` leg can watch it and no
bespoke work-done check is needed.

What makes it worth listing is the failure shape. The refit only ever PROPOSES:
it writes to `/var/lib/ktp-map-coefficients` and never to `main`. So a stopped
timer does not break anything or log anything -- the committed coefficient table
stays put and keeps serving, which is indistinguishable from "the maps have not
changed". The 2026-10-14 dry run is the measure of that: after weeks unfitted it
proposed 13 changes, one of them a map whose alive coefficient had halved.

The list is read out of the shipped script, so deleting the entry fails this file
rather than testing a copy that no longer ships.
"""
import pathlib
import re

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
TEXT = SCRIPT.read_text(encoding="utf-8")
TIMER = "ktp-map-coefficients.timer"


def critical_timers():
    """The array's entries, taken from the shipped script.

    Parsed rather than eval'd, and comment lines are dropped -- the array is
    heavily commented and every comment names other units, so a substring test
    over the raw block would pass on prose alone.
    """
    m = re.search(r"(?ms)^CRITICAL_TIMERS=\(\n(.*?)^\)", TEXT)
    assert m, "CRITICAL_TIMERS array is gone from the shipped script"
    out = []
    for ln in m.group(1).split("\n"):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def test_the_timer_is_listed():
    assert TIMER in critical_timers()


def test_it_is_listed_as_an_ENTRY_not_merely_mentioned_in_a_comment():
    """The array's comments name units that are deliberately NOT listed
    (ktp-monday-reminder.timer), so `in TEXT` would pass for an omitted unit."""
    entries = critical_timers()
    assert TIMER in entries
    assert "ktp-monday-reminder.timer" not in entries, \
        "the deliberately-omitted unit is now an entry; the parse is matching comments"


def test_every_entry_looks_like_a_timer_unit():
    for e in critical_timers():
        assert e.endswith(".timer"), "non-timer entry in CRITICAL_TIMERS: %r" % e


def test_no_duplicate_entries():
    e = critical_timers()
    assert len(e) == len(set(e)), "duplicate entries: %r" % [x for x in e if e.count(x) > 1]


def test_the_reason_survives_next_to_the_entry():
    """Keep the why, or the next reader prunes the list back."""
    block = re.search(r"(?ms)^CRITICAL_TIMERS=\(\n(.*?)^\)", TEXT).group(1)
    i = block.index(TIMER)
    preceding = block[:i]
    assert "PROPOSES" in preceding or "proposes" in preceding, \
        "the entry lost the comment explaining why a stopped timer is silent"


def test_the_unit_this_names_actually_ships():
    """A listed unit with no unit file pages forever as missing."""
    unit = SCRIPT.parent / "ktp-map-coefficients.timer"
    assert unit.is_file(), "CRITICAL_TIMERS names a timer this repo does not ship"
    body = unit.read_text(encoding="utf-8")
    assert "OnCalendar=" in body
    assert "WantedBy=timers.target" in body, "not installable; enable would be a no-op"
