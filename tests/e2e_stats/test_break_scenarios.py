"""Tests for the cap-break scenario judging.

The first version of `break_scenarios` counted `cap_break` lines in a time
window and reported a confident detector defect that did not exist — a bot had
killed a capper one second before the staged walk-off, so the break in the
window was legitimate. The lines below are copied from that run, and the first
test is the regression guard for exactly it.
"""

from __future__ import annotations

from pathlib import Path

from . import break_scenarios as bs

ROOT = Path(__file__).resolve().parents[2]

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


def test_settle_window_covers_detector_poll_and_buffer_flush_jitter():
    # Production can take one 0.5s detector poll plus one 5s stats buffer
    # period before cap_break is visible in the log.  Keep at least another
    # second of scheduling margin so the verdict cannot race that flush.
    assert bs.BreakDriver.SETTLE >= 6.5


# -- the confound that started all this ------------------------------------


def test_a_capping_team_death_just_before_the_walkoff_is_detected():
    """THE regression test. Axis was capping; an Axis player died one second
    before the walk-off, so the break in the window was legitimate and the
    scenario must be discarded rather than reported as a defect."""
    log = "\n".join([REAL_KILL, REAL_WALKOFF, REAL_BREAK])
    deaths = bs.BreakDriver._capping_deaths_near(log, bs.TEAM_AXIS)
    assert len(deaths) == 1
    assert "Andross" in deaths[0]


def test_capping_team_death_in_far_kill_window_makes_it_inconclusive():
    far = ("L 08/22/2026 - 00:52:46: [KTPBreakDrive.amxx] [BD] kill "
           "flag=3 capteam=1 mode=far victim=4 vname=Link killer=7 "
           "kname=Diablo dist=3456 count_before=2 owner_before=2")
    organic = ('L 08/22/2026 - 00:52:46: "Diablo<7><0><Axis>" killed '
               '"Claire<6><0><Allies>" with "kar"')
    deaths = bs.BreakDriver._capping_deaths_near(
        "\n".join([organic, far]), bs.TEAM_ALLIES,
        marker="[BD] kill flag=")
    assert deaths == ["Claire at 00:52:46"]


def test_far_probe_waits_past_production_candidate_ttl():
    source = (ROOT / "tests/e2e_stats/diagnostics/KTPBreakDrive.sma").read_text()
    assert "#define BD_OFFPOINT_DEATH_QUIET_SECS 4.1" in source
    assert ("get_gametime() - g_bdLastTeamDeath[team] <\n"
            "\t\t\tBD_OFFPOINT_DEATH_QUIET_SECS") in source


def test_far_probe_freezes_all_live_players_past_its_death_window():
    source = (ROOT / "tests/e2e_stats/diagnostics/KTPBreakDrive.sma").read_text()
    seconds = float(next(
        line.rsplit(" ", 1)[1]
        for line in source.splitlines()
        if line.startswith("#define BD_OFFPOINT_ISOLATION_SECS ")
    ))
    assert seconds >= bs.BreakDriver.SETTLE + 0.5
    assert "isolated = bd_begin_test_isolation()" in source
    assert 'set_task(BD_OFFPOINT_ISOLATION_SECS, "bd_isolation_end"' in source
    assert "bd_hold_test_players()" in source
    assert bs._ISOLATION_END_RE.search("[BD] isolation END")


def test_far_kill_parser_reports_isolation_coverage_and_accepts_old_logs():
    old = ("[BD] kill flag=3 capteam=1 mode=far victim=4 vname=Link "
           "killer=7 kname=Diablo dist=3456 count_before=2 owner_before=2")
    old_match = bs._KILL_RE.search(old)
    new_match = bs._KILL_RE.search(old + " isolated=12")
    assert old_match is not None and old_match.group(11) is None
    assert new_match is not None and int(new_match.group(11)) == 12


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


def test_isolation_close_waits_for_explicit_restore_marker(monkeypatch):
    prefix = "old\n"
    restored = prefix + "[BD] isolation END\norganic play resumed\n"
    driver = bs.BreakDriver(_FakeHandle([]), _FakeLog([prefix, restored]))
    sleeps = []
    monkeypatch.setattr(bs.time, "sleep", sleeps.append)

    closed, tail = driver._wait_for_isolation_end(len(prefix), timeout=1.0)

    assert closed is True
    assert bs._ISOLATION_END_RE.search(tail)
    assert "organic play resumed" not in tail
    assert sleeps == [0.05]


# -- deterministic round-restart evidence ---------------------------------


RESTART_QUEUE = (
    "L 08/20/2026 - 12:22:22: [KTPBreakDrive.amxx] [BD] restart_queue "
    "seq=4 flag=1 fname=POINT_BRIDGE capteam=1 victim=2 vname=Lara "
    "killer=7 killer_userid=7 kname=Master dist=238 count_before=2 "
    "count_queued=2 frozen=6 owner_before=0 restart_timer=1.00 "
    "round_before=702.50 drained=1"
)
RESTART_RESULT = (
    "L 08/20/2026 - 12:22:24: [KTPBreakDrive.amxx] [BD] restart_result "
    "seq=4 flag=1 fname=POINT_BRIDGE killer=7 killer_userid=7 "
    "kname=Master rebase=1 completion=1 restart_timer=1.00 "
    "round_before=702.50 "
    "round_peak=1200.80 round_after=1199.98 round_limit=1200.00 "
    "count_before=2 count_queued=2 count_after=0 frozen=6 owner_before=0 "
    "owner_after=0 contaminated=0 flushed=1"
)
RESTART_BREAK = (
    'L 08/20/2026 - 12:22:24: "Master<7><0><Axis>" triggered '
    '"cap_break" (flag "POINT_BRIDGE") (position "1 2 3")'
)


def _judge_restart(*middle, queue=RESTART_QUEUE, result=RESTART_RESULT,
                   before=(), after=()):
    return bs.BreakDriver._judge_round_restart("\n".join([
        *before, queue, *middle, result, *after,
    ]))


def test_verified_neutral_zero_to_zero_count_collapse_is_clean():
    result = _judge_restart()
    assert result.status == "ok"
    assert result.extra["queue_count_before"] == 2
    assert result.extra["queue_count_queued"] == 2
    assert result.extra["result_count_after"] == 0
    assert result.extra["queue_owner_before"] == 0
    assert result.extra["result_owner_after"] == 0

    # Any authoritative projection above the limit proves restarting; do not
    # require a large jump that a delayed scheduler poll could miss.
    small_projection = RESTART_RESULT.replace("round_peak=1200.80",
                                               "round_peak=1200.02")
    assert _judge_restart(result=small_projection).status == "ok"


def test_probe_allows_only_frozen_monotonic_rebased_collapse_before_completion():
    source = (ROOT / "tests/e2e_stats/diagnostics/KTPBreakDrive.sma").read_text()
    expected = ("if (!(g_bdRestartRebased && count >= 0 &&\n"
                "\t\t\t\t\tcount <= g_bdRestartCountQueued &&\n"
                "\t\t\t\t\tg_bdRestartFrozenCount >= g_bdRestartCountQueued &&\n"
                "\t\t\t\t\towner == g_bdRestartOwnerBefore))")
    assert expected in source
    assert source.index(expected) < source.index(
        'kind=state_before_completion count=%d owner=%d')


def test_restart_probe_freezes_world_and_userid_safely_restores_players():
    source = (ROOT / "tests/e2e_stats/diagnostics/KTPBreakDrive.sma").read_text()
    assert "g_bdRestartFrozenCount = bd_begin_test_isolation()" in source
    freeze = source[source.index("stock bd_isolate_test_players()"):
                    source.index("stock bd_hold_test_players()")]
    assert "get_user_team(id)" not in freeze
    assert "flags | FL_FROZEN | FL_GODMODE" in freeze
    assert "g_bdIsolationWasGodmode[id] = bool:(flags & FL_GODMODE)" in source
    assert "get_user_userid(id) == g_bdIsolationUserid[id]" in source
    assert "if (g_bdIsolationWasGodmode[id]) flags |= FL_GODMODE" in source
    assert "else flags &= ~FL_GODMODE" in source
    assert source.count("bd_end_test_isolation(false)") >= 3

    kill_fn = source[source.index("stock bool:bd_execute_kill"):
                     source.index("public cmd_kill()")]
    dispatch = kill_fn.index("dodx_test_dispatch_client_death(killer, victim")
    allow = kill_fn.index("bd_allow_isolated_death(victim)", dispatch)
    kill = kill_fn.index("dod_user_kill(victim)", dispatch)
    assert dispatch < allow < kill
    allow_fn = source[source.index("stock bd_allow_isolated_death(id)"):
                      source.index("stock bd_begin_test_isolation()")]
    assert "g_bdIsolationWasGodmode[id])" in allow_fn
    assert "flags & ~FL_GODMODE" in allow_fn

    insufficient = RESTART_QUEUE.replace("frozen=6", "frozen=1")
    insufficient_result = RESTART_RESULT.replace("frozen=6", "frozen=1")
    result = _judge_restart(queue=insufficient, result=insufficient_result)
    assert result.status == "not_staged"
    assert "did not freeze enough" in result.detail


def test_exact_userid_and_flag_break_after_verified_restart_is_violation():
    result = _judge_restart(RESTART_BREAK)
    assert result.status == "violation"
    assert "FALSE POSITIVE" in result.detail


def test_failed_run_ordering_is_contaminated_not_a_false_positive():
    """Organic play after the clean queue boundary beats apparent identity."""
    organic = (
        'L 08/20/2026 - 12:22:20: "Master<7><0><Axis>" killed '
        '"Fox<3><0><Allies>" with "mp40"'
    )
    contamination = (
        "L 08/20/2026 - 12:22:20: [KTPBreakDrive.amxx] "
        "[BD] restart_contamination seq=4 kind=death killer=7 victim=3"
    )
    result = _judge_restart(organic, contamination, RESTART_BREAK)
    assert result.status == "not_staged"
    assert "contaminated" in result.detail


def test_exact_failed_run_buffer_order_is_excluded_by_the_preflush_boundary():
    """Regression for run 32367384309's far-dispatch/death/late-flush order."""
    old_far = (
        "L 08/20/2026 - 12:22:19: [KTPBreakDrive.amxx] [BD] kill flag=1 "
        "capteam=1 mode=far victim=2 vname=Lara killer=7 kname=Master "
        "dist=2385 count_before=2 owner_before=0"
    )
    organic = (
        'L 08/20/2026 - 12:22:20: "Master<7><0><Axis>" killed '
        '"Fox<3><0><Allies>" with "mp40"'
    )
    # The new synchronous drain forces the old buffered cap_break before the
    # new restart_queue marker. It is outside the closed adjudication window.
    result = _judge_restart(before=(old_far, organic, RESTART_BREAK))
    assert result.status == "ok"
    assert result.breaks_seen == 0


def test_no_authoritative_restart_evidence_cannot_report_a_violation():
    no_restart = (RESTART_RESULT
                  .replace("rebase=1 completion=1", "rebase=0 completion=0")
                  .replace("round_peak=1200.80", "round_peak=701.90")
                  .replace("round_after=1199.98", "round_after=696.50")
                  .replace("count_after=0", "count_after=2"))
    result = _judge_restart(RESTART_BREAK, result=no_restart)
    assert result.status == "not_staged"
    assert "no authoritative" in result.detail


def test_ten_second_match_config_countdown_cannot_mask_candidate_expiry():
    """ktpbasic.cfg sets 10s; the probe must pin 1s or refuse the verdict."""
    timer_line = next(
        line for line in
        (ROOT / "config/local/dod-configs/ktpbasic.cfg").read_text().splitlines()
        if line.strip().startswith("mp_clan_timer ")
    )
    configured_timer = float(timer_line.split()[1])
    assert configured_timer == 10.0
    long_queue = RESTART_QUEUE.replace("restart_timer=1.00",
                                       f"restart_timer={configured_timer:.2f}")
    long_result = (RESTART_RESULT
                   .replace("restart_timer=1.00",
                            f"restart_timer={configured_timer:.2f}")
                   .replace("round_peak=1200.80",
                            f"round_peak={1200 + configured_timer - 0.2:.2f}"))

    result = _judge_restart(queue=long_queue, result=long_result)

    assert result.status == "not_staged"
    assert "2.5-second" in result.detail


def test_different_actor_or_flag_break_contaminates_instead_of_being_ignored():
    wrong_userid = RESTART_BREAK.replace("Master<7>", "Master<70>")
    wrong_flag = RESTART_BREAK.replace("POINT_BRIDGE", "POINT_PLAZA")
    for line in (wrong_userid, wrong_flag):
        result = _judge_restart(line)
        assert result.status == "not_staged"
        assert "unrelated" in result.detail

    no_flag = RESTART_BREAK.split(' (flag "')[0]
    result_unparsed = _judge_restart(no_flag)
    assert result_unparsed.status == "not_staged"
    assert "could not be parsed" in result_unparsed.detail


def test_preflush_and_postflush_markers_bound_the_restart_window():
    """Stale buffered play is before queue; later organic play is after result."""
    result = _judge_restart(before=(RESTART_BREAK,), after=(RESTART_BREAK,))
    assert result.status == "ok"
    assert result.breaks_seen == 0


def test_queue_dispatch_must_not_change_count_and_owner_must_stay_neutral():
    changed = RESTART_QUEUE.replace("count_queued=2", "count_queued=1")
    changed_result = RESTART_RESULT.replace("count_queued=2", "count_queued=1")
    result_changed = _judge_restart(queue=changed, result=changed_result)
    assert result_changed.status == "not_staged"
    assert "changed the engine capture count" in result_changed.detail

    flipped = RESTART_RESULT.replace("owner_after=0", "owner_after=1")
    result_flipped = _judge_restart(result=flipped)
    assert result_flipped.status == "not_staged"
    assert "neutral 0 -> 0" in result_flipped.detail

    for distance in (0, 513):
        outside = RESTART_QUEUE.replace("dist=238", f"dist={distance}")
        result_outside = _judge_restart(queue=outside)
        assert result_outside.status == "not_staged"
        assert "512-unit" in result_outside.detail


def test_duplicate_or_missing_restart_result_fails_closed_after_issue():
    duplicate = _judge_restart(result="\n".join([RESTART_RESULT, RESTART_RESULT]))
    assert duplicate.status == "not_staged"
    assert duplicate.extra["restart_issued"] is True

    missing = bs.BreakDriver._judge_round_restart(RESTART_QUEUE)
    assert missing.status == "not_staged"
    assert missing.extra["restart_issued"] is True


def test_live_restart_timeout_after_queue_is_one_shot(monkeypatch):
    handle = _FakeHandle([])
    observed = "old\n[BD] restart ARMED\n" + RESTART_QUEUE
    driver = bs.BreakDriver(handle, _FakeLog(["old\n", observed, observed]))
    ticks = iter((0.0, 0.0, 0.0, 0.0, 69.0))
    monkeypatch.setattr(bs.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(bs.time, "sleep", lambda _seconds: None)

    result = driver.negative_round_restart()

    assert result.status == "not_staged"
    assert result.extra["restart_issued"] is True
    assert handle.fired == ["ktp_bd_arm_restart"]


def test_inconclusive_issued_restart_is_not_retried(monkeypatch):
    calls = {"restart": 0}

    class FakeDriver:
        def __init__(self, *_args):
            pass

        @staticmethod
        def _ok(name):
            return bs.Scenario(name, status="ok")

        def negative_voluntary_walkoff(self):
            return self._ok("negative_voluntary_walkoff")

        def negative_off_point_kill(self):
            return self._ok("negative_off_point_kill")

        def negative_clean_capture(self):
            return self._ok("negative_clean_capture")

        def positive_kill_on_point(self):
            return self._ok("positive_kill_on_point")

        def negative_round_restart(self):
            calls["restart"] += 1
            return bs.Scenario("negative_round_restart",
                               extra={"restart_issued": True})

    monkeypatch.setattr(bs, "BreakDriver", FakeDriver)
    bs.run_all(object(), object(), attempts=3)
    assert calls["restart"] == 1
