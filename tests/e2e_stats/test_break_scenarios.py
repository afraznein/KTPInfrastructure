"""Tests for the cap-break scenario judging.

The first version of `break_scenarios` counted `cap_break` lines in a time
window and reported a confident detector defect that did not exist — a bot had
killed a capper one second before the staged walk-off, so the break in the
window was legitimate. The lines below are copied from that run, and the first
test is the regression guard for exactly it.
"""

from __future__ import annotations

from . import break_scenarios as bs

# Verbatim from the run that produced the false report.
REAL_BREAK = ('L 08/10/2026 - 13:18:52: "Fox<3><BOT><Allies>" triggered '
              '"cap_break" (flag "POINT_ANZIO_PLAZA") (position "1191 -264 -338")')
REAL_KILL = ('L 08/10/2026 - 13:18:46: "Fox<3><0><Allies>" killed '
             '"Andross<10><0><Axis>" with "garand"')
REAL_WALKOFF = ("L 08/10/2026 - 13:18:47: [KTPBreakDrive.amxx] [BD] walkoff "
                "flag=3 mover=4 mname=Snake anchor=6 capteam=2 count_before=2")


# -- parsing ---------------------------------------------------------------


def test_break_line_yields_the_breaker_name():
    assert bs._BREAK_RE.findall(REAL_BREAK) == ["Fox"]


def test_kill_line_yields_victim_and_victim_team():
    m = bs._KILLED_RE.match(REAL_KILL)
    assert m is not None
    assert m.group(4) == "Andross"
    assert m.group(5) == "Axis"


def test_walkoff_line_parses():
    m = bs._WALKOFF_RE.search(REAL_WALKOFF)
    assert m is not None
    assert m.group(3) == "Snake"      # mover name
    assert int(m.group(5)) == 2       # capteam = Axis
    assert int(m.group(6)) == 2       # count before


def test_timestamps_parse():
    assert bs._line_seconds(REAL_KILL) == 13 * 3600 + 18 * 60 + 46


def test_a_line_without_a_timestamp_is_none_not_zero():
    """Returning 0 would place an unstamped line at midnight and put it
    outside every window, silently disabling the contamination check."""
    assert bs._line_seconds('"A<1><BOT><Allies>" killed "B<2><BOT><Axis>"') is None


# -- the confound that started all this ------------------------------------


def test_a_capping_team_death_just_before_the_walkoff_is_detected():
    """THE regression test. Axis was capping; an Axis player died one second
    before the walk-off, so the break in the window was legitimate and the
    scenario must be discarded rather than reported as a defect."""
    log = "\n".join([REAL_KILL, REAL_WALKOFF, REAL_BREAK])
    deaths = bs.BreakDriver._capping_deaths_near(log, bs.TEAM_AXIS)
    assert len(deaths) == 1
    assert "Andross" in deaths[0]


def test_a_death_on_the_other_team_does_not_contaminate():
    """Only the capping team matters — an enemy dying nearby cannot produce a
    break against the cappers, and counting it would discard good runs."""
    log = "\n".join([REAL_KILL, REAL_WALKOFF, REAL_BREAK])
    assert bs.BreakDriver._capping_deaths_near(log, bs.TEAM_ALLIES) == []


def test_a_death_far_outside_the_window_does_not_contaminate():
    old = REAL_KILL.replace("13:18:46", "13:10:00")
    log = "\n".join([old, REAL_WALKOFF])
    assert bs.BreakDriver._capping_deaths_near(log, bs.TEAM_AXIS) == []


def test_the_lookback_reaches_backwards_as_well_as_forwards():
    """The detector holds a candidate for ~2.5s, so a kill *before* the
    walk-off is precisely what produces a legitimate break during it. A
    forward-only window would have missed the real confound."""
    before = REAL_KILL.replace("13:18:46", "13:18:44")
    after = REAL_KILL.replace("13:18:46", "13:18:50")
    for line in (before, after):
        log = "\n".join([line, REAL_WALKOFF])
        assert bs.BreakDriver._capping_deaths_near(log, bs.TEAM_AXIS), line


# -- attribution -----------------------------------------------------------


KILL_LINE = ("L 08/10/2026 - 14:24:43: [KTPBreakDrive.amxx] [BD] kill flag=3 "
             "capteam=2 mode=near victim=11 vname=Pyramid killer=1 kname=Jill "
             "dist=134 count_before=2 owner_before=1")
AFTER_LINE = "[BD] after flag=3 allies=0 axis=1 capping=1 owner=1"


def test_kill_line_parses_with_capteam_and_owner():
    """The flag is chosen by the plugin under `auto`, so the harness reads the
    capping team and owner off the line rather than assuming them."""
    m = bs._KILL_RE.search(KILL_LINE)
    assert m is not None
    assert int(m.group(2)) == 2        # capteam
    assert m.group(7) == "Jill"        # injected killer
    assert int(m.group(9)) == 2        # count before
    assert int(m.group(10)) == 1       # owner before


def test_owner_after_is_read():
    assert bs.BreakDriver._owner_after(AFTER_LINE) == 1
    assert bs.BreakDriver._owner_after("nothing") is None


def test_count_after_reads_the_capping_team_column():
    tail = "[BD] after flag=3 allies=4 axis=1 capping=1 owner=2"
    assert bs.BreakDriver._count_after(tail, bs.TEAM_ALLIES) == 4
    assert bs.BreakDriver._count_after(tail, bs.TEAM_AXIS) == 1


def test_missing_after_line_is_none_not_zero():
    """None means "did not stage"; 0 would read as "everybody left" and turn a
    missing report into a fabricated count drop."""
    assert bs.BreakDriver._count_after("nothing here", bs.TEAM_AXIS) is None


def test_abort_reason_is_surfaced():
    tail = "[BD] kill ABORT flag=2 no qualifying player"
    assert "no qualifying player" in bs.BreakDriver._abort_reason(tail)


def test_no_abort_reads_as_none():
    assert bs.BreakDriver._abort_reason("[BD] scan done flags=5") is None


# -- the deaths-nearby helper is now shared -------------------------------


def test_deaths_helper_anchors_on_the_marker_it_is_given():
    """`_capping_deaths_near` is used by both the walk-off and the clean-cap
    scenarios, which anchor on different log lines. Hardcoding the walk-off
    marker would make the clean-cap check anchor on nothing and silently find
    no deaths — i.e. report every window as clean."""
    log = "\n".join([
        REAL_KILL,
        "L 08/10/2026 - 13:18:47: [KTPBreakDrive.amxx] [BD] scan done flags=5",
    ])
    assert bs.BreakDriver._capping_deaths_near(
        log, bs.TEAM_AXIS, marker="ktp_bd_scan") == [], "no marker line present"
    found = bs.BreakDriver._capping_deaths_near(
        log, bs.TEAM_AXIS, marker="[BD] scan done")
    assert len(found) == 1 and "Andross" in found[0]


def test_deaths_helper_still_defaults_to_the_walkoff_marker():
    log = "\n".join([REAL_KILL, REAL_WALKOFF])
    assert len(bs.BreakDriver._capping_deaths_near(log, bs.TEAM_AXIS)) == 1


# -- the capture gate --------------------------------------------------


class _FakeHandle:
    """Records rcon calls; scan responses are scripted per call."""

    def __init__(self, scan_responses):
        self._responses = list(scan_responses)
        self.fired = []

    def rcon(self, cmd):
        if cmd == "ktp_bd_scan":
            # BreakDriver.scan() reads the log after issuing this; the fake
            # short-circuits by handing scan() its next canned answer via a
            # monkeypatched _read, so this branch just records nothing.
            return
        self.fired.append(cmd)


class _FakeLog:
    def __init__(self, reads):
        self.reads = list(reads)
        self.index = 0

    def read_text(self, **_kwargs):
        i = min(self.index, len(self.reads) - 1)
        self.index += 1
        return self.reads[i]


def test_scan_returns_as_soon_as_terminator_arrives(monkeypatch):
    prefix = "existing log\n"
    response = (prefix +
                "[BD] flag 3 name=POINT_ANZIO_PLAZA owner=1 capping=1 "
                "capteam=2 allies=0 axis=2\n[BD] scan done flags=5\n")
    log = _FakeLog([prefix, prefix, response])
    driver = bs.BreakDriver(_FakeHandle([]), log)
    sleeps = []
    monkeypatch.setattr(bs.time, "sleep", sleeps.append)

    assert driver.scan() == [{
        "flag": 3, "name": "POINT_ANZIO_PLAZA", "owner": 1,
        "capping": 1, "capteam": 2, "allies": 0, "axis": 2,
    }]
    assert sleeps == [0.05]


def test_arm_kill_waits_for_plugin_to_stage(monkeypatch):
    """The settle window starts only after HLDS confirms the staged kill."""
    from . import break_scenarios as bs

    handle = _FakeHandle([])
    log = _FakeLog(["old\n", "old\n", "old\n" + KILL_LINE])
    driver = bs.BreakDriver(handle, log)
    sleeps = []
    monkeypatch.setattr(bs.time, "sleep", sleeps.append)

    ok = driver._arm_kill("near", timeout=5.0, poll=0.01)
    assert ok is True
    assert handle.fired == ["ktp_bd_arm_kill near"]
    assert sleeps == [0.01]


def test_arm_kill_reports_plugin_abort(monkeypatch):
    from . import break_scenarios as bs

    handle = _FakeHandle([])
    abort = "[BD] kill ABORT flag=-1 mode=far no stageable capture while armed"
    driver = bs.BreakDriver(handle, _FakeLog(["old\n", "old\n" + abort]))

    ok = driver._arm_kill("far", timeout=5.0, poll=0.01)
    assert ok is False
    assert handle.fired == ["ktp_bd_arm_kill far"]
