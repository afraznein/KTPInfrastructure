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


def test_far_probe_prepares_a_real_capture_and_is_bounded_before_halftime():
    source = (ROOT / "tests/e2e_stats/diagnostics/KTPBreakDrive.sma").read_text()
    assert 0 < bs.BreakDriver.FAR_STAGE_TIMEOUT <= 15.0
    assert bs.BreakDriver.SERIES_TIMEOUT < 20 * 60
    assert "#define BD_FAR_KILL_MAX_POLLS BD_KILL_MAX_POLLS" in source
    arm = source[source.index("public cmd_arm_kill()"):
                 source.index("public bd_kill_poll()")]
    assert arm.index("remove_task(BD_TASK_KILL_POLL)") < arm.index(
        "g_bdKillPolls = 0"
    ) < arm.index("bd_prepare_capture(") < arm.index(
        'set_task(0.1, "bd_kill_poll"'
    )
    prepare = source[source.index("stock bool:bd_prepare_capture"):
                     source.index("stock bd_find_prepared_capture")]
    assert "bd_area_center" in prepare
    assert "dodx_set_user_origin(id, anchor)" in prepare
    assert "dodx_set_user_origin(id, center)" in prepare
    assert "CA_timetocap, BD_PREPARED_CAPTURE_SECS" in prepare
    poll = source[source.index("public bd_kill_poll()"):
                  source.index("stock bool:bd_execute_restart")]
    assert "g_bdKillNear ? BD_KILL_MAX_POLLS : BD_FAR_KILL_MAX_POLLS" in poll
    assert 'register_srvcmd("ktp_bd_disarm_kill", "cmd_disarm_kill")' in source
    disarm = source[source.index("public cmd_disarm_kill()"):
                    source.index("public bd_kill_poll()")]
    assert "remove_task(BD_TASK_KILL_POLL)" in disarm
    assert 'server_print("KTP_BD_KILL_DISARMED")' in disarm


def test_both_kill_probes_freeze_all_live_players_past_the_evidence_window():
    source = (ROOT / "tests/e2e_stats/diagnostics/KTPBreakDrive.sma").read_text()
    seconds = float(next(
        line.rsplit(" ", 1)[1]
        for line in source.splitlines()
        if line.startswith("#define BD_KILL_ISOLATION_SECS ")
    ))
    assert seconds >= bs.BreakDriver.SETTLE + 0.5
    assert "isolated = bd_begin_test_isolation()" in source
    assert 'set_task(BD_KILL_ISOLATION_SECS, "bd_isolation_end"' in source
    assert "bd_hold_test_players()" in source
    assert bs._ISOLATION_END_RE.search("[BD] isolation END")

    kill_fn = source[source.index("stock bool:bd_execute_kill"):
                     source.index("public cmd_kill()")]
    victim = kill_fn.index("new victim = bd_pick")
    killer = kill_fn.index("new killer = bd_pick_enemy")
    isolate = kill_fn.index("isolated = g_bdIsolationActive ?")
    dispatch = kill_fn.index("dodx_test_dispatch_client_death(killer, victim")
    allow = kill_fn.index("bd_allow_isolated_death(victim)", dispatch)
    kill = kill_fn.index("dod_user_kill(victim)", dispatch)
    assert victim < killer < isolate < dispatch < allow < kill
    assert "if (!want_near) {" not in kill_fn[isolate:kill]


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
             "dist=134 count_before=2 owner_before=1 isolated=12")
AFTER_LINE = "[BD] after flag=3 allies=0 axis=1 capping=1 owner=1"
BREAK_LINE = ('L 08/10/2026 - 14:24:44: "Jill<1><0><Allies>" triggered '
              '"cap_break" (flag "POINT_ANZIO_PLAZA") (position "1 2 3")')


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
        if cmd == "ktp_bd_disarm_kill":
            return "KTP_BD_KILL_DISARMED"
        if cmd.startswith("ktp_bd_abort_series "):
            return "KTP_BD_SERIES_ABORTED"
        if cmd == "ktp_bd_begin_series":
            return "KTP_BD_SERIES_BEGUN"
        if cmd == "ktp_bd_end_series":
            return "KTP_BD_SERIES_ENDED"


class _FakeLog:
    def __init__(self, reads):
        self.reads = list(reads)
        self.index = 0

    def read_text(self, **_kwargs):
        i = min(self.index, len(self.reads) - 1)
        self.index += 1
        return self.reads[i]


def _match_start(match_id, half="1st half"):
    return (f'L 08/28/2026 - 12:00:00: KTP_MATCH_START '
            f'(matchid "{match_id}") (map "dod_anzio") '
            f'(half "{half}") (type "0")\n')


def _manifest(match_id, half=1, epoch=100, producer="stats_logging"):
    return (f'L 08/28/2026 - 12:00:00: KTP_CAPTURE_MANIFEST '
            f'(matchid "{match_id}") (half "{half}") '
            f'(map "dod_anzio") (producer "{producer}") '
            f'(producer_version "1.18.1") (schema "22") '
            f'(capabilities "frag_context,damage,position,health") '
            f'(position_interval "2.0") (buffer_entries "128") '
            f'(life_buffer_entries "64") (sequence "1") '
            f'(event_epoch "{epoch}")\n')


def _match_end(match_id):
    return (f'L 08/28/2026 - 12:00:10: KTP_MATCH_END '
            f'(matchid "{match_id}") (map "dod_anzio")\n')


def _plugin_load():
    return ("L 08/28/2026 - 12:00:10: [KTPBreakDrive.amxx] "
            "[BD] loaded — NOT FOR PRODUCTION\n")


def test_begin_series_accepts_start_before_matching_manifest_without_rcon_race():
    text = (_match_start("clean-report") + _manifest("clean-report", epoch=90)
            + _match_end("clean-report")
            + _match_start("diagnostic-TEST")
            + _manifest("diagnostic-TEST", epoch=100))
    handle = _FakeHandle([])
    driver = bs.BreakDriver(handle, _FakeLog([text]))

    assert driver.begin_series() is True
    assert driver.series_manifest == ("diagnostic-TEST", 1, 100)
    assert handle.fired == ["ktp_bd_begin_series"]


def test_begin_series_accepts_real_r3_manifest_before_start_order():
    text = (_match_start("clean-report") + _manifest("clean-report", epoch=90)
            + _match_end("clean-report")
            + _manifest("diagnostic-TEST", epoch=100)
            + _match_start("diagnostic-TEST"))
    handle = _FakeHandle([])
    driver = bs.BreakDriver(handle, _FakeLog([text]))

    assert driver.begin_series() is True
    assert driver.series_manifest == ("diagnostic-TEST", 1, 100)
    assert handle.fired == ["ktp_bd_begin_series"]


def test_begin_series_waits_for_unique_binding_before_first_rcon(monkeypatch):
    start = _match_start("diagnostic-TEST")
    handle = _FakeHandle([])
    driver = bs.BreakDriver(
        handle, _FakeLog([start, start + _manifest("diagnostic-TEST")])
    )
    sleeps = []
    monkeypatch.setattr(bs.time, "sleep", sleeps.append)

    assert driver.begin_series() is True
    assert sleeps == [0.05]
    assert handle.fired == ["ktp_bd_begin_series"]


def test_begin_series_rejects_clean_missing_or_stale_manifest_without_rcon():
    cases = [
        (
            _match_start("clean-report") + _manifest("clean-report"),
            "current_match_not_diagnostic",
        ),
        (
            _manifest("diagnostic-TEST")
            + _match_end("diagnostic-TEST")
            + _match_start("diagnostic-TEST"),
            "current_manifest_missing",
        ),
        (
            _manifest("diagnostic-TEST")
            + _plugin_load()
            + _match_start("diagnostic-TEST"),
            "current_manifest_missing",
        ),
        (
            _manifest("diagnostic-TEST")
            + _match_start("diagnostic-TEST")
            + _manifest("foreign-TEST", epoch=101),
            "current_manifest_foreign",
        ),
        (
            _manifest("diagnostic-TEST", epoch=100)
            + _match_start("diagnostic-TEST")
            + _manifest("diagnostic-TEST", epoch=101),
            "current_manifest_ambiguous",
        ),
        (
            _match_start("diagnostic-TEST")
            + _manifest("diagnostic-TEST")
            + "L 08/28/2026 - 12:00:10: KTP_HALF_END\n",
            "current_match_lifecycle_closed",
        ),
        (
            _manifest("diagnostic-TEST")
            + _match_start("diagnostic-TEST")
            + _match_end("diagnostic-TEST"),
            "current_match_lifecycle_closed",
        ),
        (
            _manifest("diagnostic-TEST")
            + _match_start("diagnostic-TEST")
            + _plugin_load(),
            "current_match_lifecycle_closed",
        ),
    ]
    for text, reason in cases:
        handle = _FakeHandle([])
        driver = bs.BreakDriver(handle, _FakeLog([text]))
        driver.MANIFEST_WAIT_TIMEOUT = 0.0

        assert driver.begin_series() is False
        assert driver.series_abort_reason == reason
        assert handle.fired == []
        assert driver.series_started is False


def test_current_manifest_binding_normalizes_ot_half_number():
    text = (_match_start("diagnostic-TEST", "OT 1")
            + _manifest("diagnostic-TEST", half=101, epoch=200))
    assert bs.BreakDriver._current_diagnostic_manifest(text) == (
        ("diagnostic-TEST", 101, 200), ""
    )


def _marker_payload(engine_line):
    return engine_line.split(": ", 1)[1].rstrip("\n")


def test_manifest_parser_rejects_chat_plugin_echo_and_bad_producer_before_rcon():
    manifest_payload = _marker_payload(_manifest("diagnostic-TEST"))
    start = _match_start("diagnostic-TEST")
    imitations = [
        (
            'L 08/28/2026 - 12:00:00: '
            f'"Imitator<1><STEAM_0:1:1><Allies>" say "{manifest_payload}"\n'
            + start
        ),
        (
            "L 08/28/2026 - 12:00:00: [Echo.amxx] "
            + manifest_payload + "\n" + start
        ),
        _manifest("diagnostic-TEST", producer="echo") + start,
        _manifest("diagnostic-TEST").replace(
            '(producer "stats_logging") ', ""
        ) + start,
    ]
    for text in imitations:
        handle = _FakeHandle([])
        driver = bs.BreakDriver(handle, _FakeLog([text]))
        driver.MANIFEST_WAIT_TIMEOUT = 0.0

        assert driver.begin_series() is False
        assert driver.series_abort_reason == "current_manifest_missing"
        assert handle.fired == []


def test_match_start_parser_rejects_chat_and_generic_plugin_echo():
    start_payload = _marker_payload(_match_start("diagnostic-TEST"))
    manifest = _manifest("diagnostic-TEST")
    imitations = [
        (
            manifest + 'L 08/28/2026 - 12:00:00: '
            f'"Imitator<1><STEAM_0:1:1><Allies>" say "{start_payload}"\n'
        ),
        (
            manifest + "L 08/28/2026 - 12:00:00: [Echo.amxx] "
            + start_payload + "\n"
        ),
    ]
    for text in imitations:
        handle = _FakeHandle([])
        driver = bs.BreakDriver(handle, _FakeLog([text]))
        driver.MANIFEST_WAIT_TIMEOUT = 0.0

        assert driver.begin_series() is False
        assert driver.series_abort_reason == "current_match_start_missing"
        assert handle.fired == []


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
    assert handle.fired == ["ktp_bd_arm_kill far", "ktp_bd_disarm_kill"]
    assert driver.last_kill_disarm_ack is True


def test_arm_kill_timeout_disarms_and_requires_ack(monkeypatch):
    handle = _FakeHandle([])
    driver = bs.BreakDriver(handle, _FakeLog(["old\n"] * 5))
    ticks = iter((0.0, 0.0, 5.1))
    monkeypatch.setattr(bs.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(bs.time, "sleep", lambda _seconds: None)

    assert driver._arm_kill("far", timeout=5.0) is False
    assert handle.fired == ["ktp_bd_arm_kill far", "ktp_bd_disarm_kill"]
    assert driver.last_kill_disarm_ack is True


def test_arm_kill_timeout_without_disarm_ack_fails_closed(monkeypatch):
    class NoAckHandle:
        def __init__(self):
            self.fired = []

        def rcon(self, command):
            self.fired.append(command)
            return None

    handle = NoAckHandle()
    driver = bs.BreakDriver(handle, _FakeLog(["old\n"] * 8))
    ticks = iter((0.0, 5.1, 5.1, 7.2))
    monkeypatch.setattr(bs.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(bs.time, "sleep", lambda _seconds: None)

    assert driver._arm_kill("far", timeout=5.0) is False
    assert handle.fired == ["ktp_bd_arm_kill far", "ktp_bd_disarm_kill"]
    assert driver.last_kill_disarm_ack is False


def test_half_end_before_arm_aborts_and_never_queues_a_kill():
    prefix = "old\n"
    handle = _FakeHandle([])
    driver = bs.BreakDriver(
        handle, _FakeLog([prefix + "KTP_HALF_END match\n"] * 5)
    )
    driver.series_started = True
    driver.series_mark = len(prefix)
    driver.series_deadline = bs.time.monotonic() + 60.0

    assert driver._arm_kill("near") is False
    assert "ktp_bd_arm_kill near" not in handle.fired
    assert handle.fired == [
        "ktp_bd_abort_series half_end", "ktp_bd_disarm_kill",
    ]
    assert driver.series_abort_reason == "half_end"
    assert driver.last_kill_disarm_ack is True


def test_manifest_activation_plugin_reload_and_userid_epoch_are_boundaries():
    prefix = _manifest("diagnostic-TEST", epoch=100)
    cases = {
        "manifest_activation_epoch_change": _manifest(
            "diagnostic-TEST", epoch=101
        ),
        "plugin_reload": "[BD] loaded -- NOT FOR PRODUCTION\n",
        "userid_epoch_change": (
            "[BD] series ABORT reason=userid_epoch_change\n"
        ),
    }
    for expected, appended in cases.items():
        driver = bs.BreakDriver(
            _FakeHandle([]), _FakeLog([prefix + appended] * 3)
        )
        driver.series_started = True
        driver.series_mark = len(prefix)
        driver.series_manifest = ("diagnostic-TEST", 1, 100)
        driver.series_deadline = bs.time.monotonic() + 60.0
        assert driver._boundary_reason() == expected


def test_pawn_series_abort_removes_mutators_and_guards_every_arm_command():
    source = (ROOT / "tests/e2e_stats/diagnostics/KTPBreakDrive.sma").read_text()
    assert "public server_changelevel(map[])" in source
    assert "public ktp_half_end(" in source
    assert "bd_abort_series(\"half_end\", true)" in source
    assert "public ktp_match_end(" in source
    assert "bd_abort_series(\"match_end\", true)" in source
    assert "public client_putinserver(id)" in source
    assert "public client_disconnected(id)" in source
    cleanup = source[source.index("stock bd_cleanup_tasks()"):
                     source.index("stock bd_abort_series")]
    for task in (
        "BD_TASK_KILL_POLL", "BD_TASK_WALKOFF_POLL",
        "BD_TASK_RESTART_ARM_POLL", "BD_TASK_RESTART_POLL",
        "BD_TASK_RESTART_FINISH",
    ):
        assert f"remove_task({task})" in cleanup
    for command in ("cmd_arm_kill", "cmd_arm_restart", "cmd_arm_walkoff"):
        body = source[source.index(f"public {command}()"):
                      source.index("}", source.index(f"public {command}()"))]
        assert "bd_series_guard" in body


def test_pawn_abort_and_end_cancel_and_guard_delayed_after_reports():
    source = (ROOT / "tests/e2e_stats/diagnostics/KTPBreakDrive.sma").read_text()
    cleanup = source[source.index("stock bd_cleanup_tasks()"):
                     source.index("stock bd_abort_series")]
    assert "remove_task(BD_TASK_REPORT_BASE + f)" in cleanup
    assert 'set_task(1.5, "bd_report_after", f)' not in source
    assert 'set_task(1.5, "bd_report_after", taskid)' in source

    callback = source[source.index("public bd_report_after(taskid)"):
                      source.index("/**", source.index(
                          "public bd_report_after(taskid)"))]
    assert "if (!g_bdSeriesActive)" in callback
    assert "return PLUGIN_HANDLED" in callback

    abort = source[source.index("stock bd_abort_series"):
                   source.index("stock bool:bd_series_guard")]
    end = source[source.index("public cmd_end_series()"):
                 source.index("public cmd_clock_preflight()")]
    for body in (abort, end):
        assert body.index("g_bdSeriesActive = false") < body.index(
            "bd_cleanup_tasks()"
        )


def test_far_arm_default_refuses_to_wait_for_a_random_capture_drought(monkeypatch):
    handle = _FakeHandle([])
    abort = "[BD] kill ABORT flag=-1 mode=far no stageable capture while armed"
    log = _FakeLog(["old\n", "old\n" + abort])
    driver = bs.BreakDriver(handle, log)

    assert driver._arm_kill("far") is False
    assert handle.fired == ["ktp_bd_arm_kill far", "ktp_bd_disarm_kill"]
    assert driver.last_kill_disarm_ack is True


def test_forced_no_capture_returns_not_staged_with_disarm_before_half_budget(
        monkeypatch):
    abort = "[BD] kill ABORT flag=-1 mode=far no stageable capture while armed"
    driver = bs.BreakDriver(
        _FakeHandle([]), _FakeLog(["old\n", "old\n" + abort])
    )
    driver.last_kill_disarm_ack = True
    monkeypatch.setattr(driver, "_arm_kill", lambda _mode: False)

    result = driver.negative_off_point_kill()

    assert result.status == "not_staged"
    assert "plugin aborted" in result.detail
    assert result.extra["kill_disarm_ack"] is True
    assert bs.BreakDriver.FAR_STAGE_TIMEOUT < bs.BreakDriver.SERIES_TIMEOUT


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


def _positive_result(monkeypatch, tail, *, closed=True):
    driver = bs.BreakDriver(_FakeHandle([]), _FakeLog(["old\n"]))
    monkeypatch.setattr(driver, "_arm_kill", lambda _mode: True)
    monkeypatch.setattr(driver, "_wait_for_isolation_end",
                        lambda _mark: (closed, tail))
    monkeypatch.setattr(bs.time, "sleep", lambda _seconds: None)
    return driver.positive_kill_on_point()


def test_positive_count_drop_named_break_and_close_passes(monkeypatch):
    tail = "\n".join([KILL_LINE, AFTER_LINE, BREAK_LINE,
                       "[BD] isolation END"])
    result = _positive_result(monkeypatch, tail)

    assert result.status == "ok"
    assert result.breaks_seen == 1
    assert result.extra["isolated_players"] == 12


def test_positive_ignores_organic_lines_after_isolation_end(monkeypatch):
    prefix = "old\n"
    organic = ('L 08/10/2026 - 14:24:50: "Organic<8><0><Axis>" triggered '
               '"cap_break" (flag "POINT_ANZIO_PLAZA") (position "4 5 6")')
    complete = prefix + "\n".join([
        KILL_LINE, AFTER_LINE, BREAK_LINE, "[BD] isolation END", organic,
    ])
    driver = bs.BreakDriver(
        _FakeHandle([]),
        _FakeLog([prefix, prefix, prefix + KILL_LINE, complete]),
    )
    monkeypatch.setattr(bs.time, "sleep", lambda _seconds: None)

    result = driver.positive_kill_on_point()

    assert result.status == "ok"
    assert result.breaks_seen == 1
    assert result.extra["breakers"] == ["Jill"]


def test_positive_missing_or_weak_isolation_is_not_staged(monkeypatch):
    evidence = "\n".join([KILL_LINE, AFTER_LINE, BREAK_LINE,
                            "[BD] isolation END"])

    weak = _positive_result(
        monkeypatch, evidence.replace("isolated=12", "isolated=1"))
    assert weak.status == "not_staged"
    assert "not isolated" in weak.detail

    missing_coverage = _positive_result(
        monkeypatch, evidence.replace(" isolated=12", ""))
    assert missing_coverage.status == "not_staged"
    assert "not isolated" in missing_coverage.detail

    missing_close = _positive_result(monkeypatch, evidence, closed=False)
    assert missing_close.status == "not_staged"
    assert "close marker" in missing_close.detail


# -- deterministic round-restart evidence ---------------------------------


class _RestartArmModel:
    """Small executable model of the Pawn arm phases and pinned-roster gate."""

    STABLE_POLLS = 5

    def __init__(self, players):
        self.players = players
        self.pinned = {
            player_id: (row["userid"], row["team"], row["generation"])
            for player_id, row in players.items()
            if row["team"] in (bs.TEAM_ALLIES, bs.TEAM_AXIS)
        }
        self.phase = "normalizing"
        self.stable_generation = None
        self.stable_polls = 0
        self.prepared = 0
        self.queues = 0
        self.results = 0
        self.aborted = False

    def _complete(self, *, stable):
        combat = {
            player_id: row for player_id, row in self.players.items()
            if row["team"] in (bs.TEAM_ALLIES, bs.TEAM_AXIS)
        }
        if set(combat) != set(self.pinned):
            return False
        for player_id, row in combat.items():
            userid, team, baseline = self.pinned[player_id]
            if (row["userid"], row["team"]) != (userid, team):
                return False
            if stable:
                if row["generation"] != self.stable_generation[player_id]:
                    return False
            elif not baseline <= row["generation"] <= baseline + 1:
                return False
        return True

    def lifecycle_abort(self):
        self.aborted = True
        self.phase = "aborted"

    def tick(self, *, clock_complete=False, area_stable=True,
             capture_active=False, finish=False):
        if self.aborted or self.phase == "done":
            return
        expects_stable = (self.phase == "prepared" or
                          self.stable_generation is not None)
        if not self._complete(stable=expects_stable):
            self.lifecycle_abort()
            return
        if self.phase == "normalizing":
            if clock_complete:
                self.phase = "stabilizing"
            return
        if self.phase == "stabilizing":
            if self.stable_generation is None:
                if (not area_stable or any(
                        not row["alive"] or
                        row["generation"] != self.pinned[player_id][2] + 1
                        for player_id, row in self.players.items()
                        if player_id in self.pinned)):
                    return
                self.stable_generation = {
                    player_id: row["generation"]
                    for player_id, row in self.players.items()
                    if player_id in self.pinned
                }
                return
            if not area_stable:
                self.stable_generation = None
                self.stable_polls = 0
                return
            self.stable_polls += 1
            if self.stable_polls >= self.STABLE_POLLS:
                self.prepared += 1
                self.phase = "prepared"
            return
        if self.phase == "prepared" and capture_active:
            self.queues += 1
            self.phase = "issued"
            return
        if self.phase == "issued" and finish:
            self.results += 1
            self.phase = "done"


def _restart_model_at_prepared(players):
    model = _RestartArmModel(players)
    model.tick(clock_complete=True)
    for row in players.values():
        if row["team"] in (bs.TEAM_ALLIES, bs.TEAM_AXIS):
            row["generation"] += 1
    model.tick()
    for _ in range(model.STABLE_POLLS):
        model.tick()
    assert model.phase == "prepared"
    return model


def test_restart_arm_behavior_waits_for_respawn_and_aborts_membership_changes():
    def roster(*, spectator=False):
        players = {
            1: {"userid": 101, "team": bs.TEAM_ALLIES,
                "generation": 7, "alive": True},
            2: {"userid": 202, "team": bs.TEAM_AXIS,
                "generation": 4, "alive": True},
        }
        if spectator:
            players[3] = {"userid": 303, "team": 0,
                          "generation": 2, "alive": True}
        return players

    # r5 ordering: the clock normalizes first. No capture is prepared until a
    # later spawn generation and all five stable post-respawn samples exist.
    players = roster()
    model = _RestartArmModel(players)
    model.tick(clock_complete=True)
    assert model.phase == "stabilizing"
    model.tick()
    assert model.prepared == model.queues == model.results == 0
    for row in players.values():
        row["generation"] += 1
    model.tick()
    assert model.stable_generation is not None
    for _ in range(model.STABLE_POLLS - 1):
        model.tick()
    assert model.prepared == model.queues == 0
    model.tick()
    assert model.prepared == 1 and model.queues == 0
    model.tick(capture_active=True)
    model.tick(finish=True)
    model.tick(capture_active=True, finish=True)
    assert (model.queues, model.results) == (1, 1)

    # An already-connected spectator joining combat never changed the userid
    # epoch in r5. Pinned-roster completeness must still abort immediately.
    entrants = roster(spectator=True)
    entrant_model = _RestartArmModel(entrants)
    entrants[3]["team"] = bs.TEAM_ALLIES
    entrant_model.tick()
    assert entrant_model.aborted is True
    assert entrant_model.queues == entrant_model.results == 0

    # Lifecycle cleanup disarms the prepared callback; a later active capture
    # observation cannot resurrect a queue or result.
    lifecycle_model = _restart_model_at_prepared(roster())
    lifecycle_model.lifecycle_abort()
    lifecycle_model.tick(capture_active=True)
    lifecycle_model.tick(finish=True)
    assert lifecycle_model.queues == lifecycle_model.results == 0


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


def test_clean_capture_boundary_during_settle_aborts_instead_of_scoring_ok(
        monkeypatch):
    driver = bs.BreakDriver(_FakeHandle([]), _FakeLog(["old\n"] * 3))
    driver.series_started = True
    driver.series_deadline = bs.time.monotonic() + 60.0
    scans = iter([
        [{"flag": 0, "owner": 0}],
        [{"flag": 0, "owner": bs.TEAM_ALLIES}],
    ])
    monkeypatch.setattr(driver, "scan", lambda: next(scans))
    sleeps = {"count": 0}

    def guarded_sleep(_seconds):
        sleeps["count"] += 1
        if sleeps["count"] == 1:
            return True
        driver.series_abort_reason = "half_end"
        driver.series_abort_ack = True
        return False

    monkeypatch.setattr(driver, "_series_sleep", guarded_sleep)

    result = driver.negative_clean_capture()

    assert result.status == "not_staged"
    assert result.extra["series_abort"] == "half_end"
    assert result.extra["series_abort_ack"] is True
    assert sleeps["count"] == 2


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


def test_normalization_clock_before_respawn_cannot_prepare_or_queue_early():
    """Regression for r5 runs 1-4: PREPARED preceded bot respawns by ~1s."""
    source = (ROOT / "tests/e2e_stats/diagnostics/KTPBreakDrive.sma").read_text()
    polls = int(next(
        line.rsplit(" ", 1)[1]
        for line in source.splitlines()
        if line.startswith("#define BD_RESTART_POSTRESPAWN_STABLE_POLLS ")
    ))
    assert polls >= 5
    assert "public dod_client_spawn(id)" in source
    assert "g_bdSpawnGeneration[id]++" in source

    arm = source[source.index("public cmd_arm_restart()"):
                 source.index("public bd_restart_arm_poll()")]
    assert arm.index("bd_snapshot_restart_roster()") < arm.index(
        'server_cmd("mp_clan_restartround 1")'
    )

    poll = source[source.index("public bd_restart_arm_poll()"):
                  source.index("public bd_restart_poll()")]
    normalizing_start = poll.index(
        "g_bdRestartArmPhase == BD_RESTART_ARM_NORMALIZING"
    )
    stabilizing_start = poll.index(
        "g_bdRestartArmPhase == BD_RESTART_ARM_STABILIZING",
        normalizing_start,
    )
    normalizing = poll[normalizing_start:stabilizing_start]
    assert "g_bdRestartNormalizeRebased" in normalizing
    assert "g_bdRestartArmPhase = BD_RESTART_ARM_STABILIZING" in normalizing
    # The clock transition ends this callback. It cannot fall through and
    # prepare using the old generation in the same frame.
    assert normalizing.rfind("return PLUGIN_HANDLED") > normalizing.index(
        "g_bdRestartArmPhase = BD_RESTART_ARM_STABILIZING"
    )

    prepared_start = poll.index(
        "g_bdRestartArmPhase == BD_RESTART_ARM_PREPARED", stabilizing_start
    )
    stabilizing = poll[stabilizing_start:prepared_start]
    assert stabilizing.index("bd_restart_roster_respawned()") < (
        stabilizing.index("bd_restart_begin_stability(")
    ) < stabilizing.index("bd_restart_stability_current()")
    threshold = stabilizing.index("BD_RESTART_POSTRESPAWN_STABLE_POLLS")
    prepare = stabilizing.index('bd_prepare_capture("restart"')
    assert threshold < prepare
    assert "g_bdRestartArmPhase = BD_RESTART_ARM_PREPARED" in stabilizing
    assert stabilizing.rfind("return PLUGIN_HANDLED") > stabilizing.index(
        "g_bdRestartArmPhase = BD_RESTART_ARM_PREPARED"
    )

    prepared = poll[prepared_start:]
    assert prepared.index("bd_restart_roster_generation_current()") < (
        prepared.index("bd_find_prepared_capture()")
    ) < prepared.index("bd_execute_restart(f)")
    # One issued identity and one result identity remain the only successful
    # restart markers in the plugin.
    assert source.count('log_amx("[BD] restart_queue ') == 1
    assert source.count('log_amx("[BD] restart_result ') == 1


def test_restart_stability_refreshes_isolation_on_a_new_spawn_generation():
    source = (ROOT / "tests/e2e_stats/diagnostics/KTPBreakDrive.sma").read_text()
    hold = source[source.index("stock bd_hold_test_players()"):
                  source.index("stock bd_allow_isolated_death(id)")]
    restore = source[source.index("stock bd_restore_isolated_players()"):
                     source.index("stock bd_restore_prepared_capture()")]
    assert ("g_bdIsolationSpawnGeneration[id] != "
            "g_bdSpawnGeneration[id]") in hold
    assert ("g_bdIsolationSpawnGeneration[id] = "
            "g_bdSpawnGeneration[id]") in hold
    assert ("g_bdSpawnGeneration[id] == "
            "g_bdIsolationSpawnGeneration[id]") in restore


def test_restart_never_fires_late_when_respawn_or_lifecycle_stability_fails():
    source = (ROOT / "tests/e2e_stats/diagnostics/KTPBreakDrive.sma").read_text()
    assert bs.BreakDriver.SERIES_TIMEOUT == 300.0
    completeness = source[source.index(
        "stock bool:bd_restart_roster_pinned_complete"
    ):source.index("stock bool:bd_restart_roster_respawned")]
    assert "get_players(players, num)" in completeness
    assert "!g_bdRestartRosterSelected[id]" in completeness
    assert "team != g_bdRestartRosterTeam[id]" in completeness
    assert "g_bdRestartRosterSpawnBaseline[id] + 1" in completeness
    assert "g_bdRestartRosterSpawnStable[id]" in completeness
    abort = source[source.index("stock bd_restart_arm_abort"):
                   source.index("/** Create a real, bounded capture")]
    assert abort.index("remove_task(BD_TASK_RESTART_ARM_POLL)") < (
        abort.index('log_amx("[BD] restart ABORT')
    ) < abort.index("bd_end_test_isolation(false)")
    assert "bd_restore_restart_timer()" in abort
    assert "bd_reset_restart_arm_state()" in abort

    poll = source[source.index("public bd_restart_arm_poll()"):
                  source.index("public bd_restart_poll()")]
    assert poll.index("g_bdRestartArmPolls >= BD_KILL_MAX_POLLS") < (
        poll.index("g_bdRestartArmPhase == BD_RESTART_ARM_NORMALIZING")
    )
    assert poll.index("bd_restart_roster_pinned_complete(stable_generation)") < (
        poll.index("g_bdRestartArmPhase == BD_RESTART_ARM_NORMALIZING")
    )
    assert 'bd_restart_arm_abort("combat roster changed while restart armed")' in poll
    assert 'bd_restart_arm_abort("roster respawned after capture preparation")' in poll

    lifecycle = source[source.index("public ktp_half_end("):
                       source.index("stock bd_reset_restart_arm_state()")]
    assert 'bd_abort_series("half_end", true)' in lifecycle
    assert 'bd_abort_series("match_end", true)' in lifecycle
    cleanup = source[source.index("stock bd_cleanup_tasks()"):
                     source.index("stock bd_abort_series")]
    assert "remove_task(BD_TASK_RESTART_ARM_POLL)" in cleanup
    restart = source[source.index("stock bool:bd_execute_restart"):
                     source.index("public cmd_arm_restart()")]
    assert "\n\tdod_user_kill(" not in restart


def test_restart_probe_freezes_world_and_userid_safely_restores_players():
    source = (ROOT / "tests/e2e_stats/diagnostics/KTPBreakDrive.sma").read_text()
    assert ("g_bdRestartFrozenCount = g_bdIsolationActive ?\n"
            "\t\tbd_isolation_count() : bd_begin_test_isolation()") in source
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

        def begin_series(self):
            return True

        def end_series(self):
            return True

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


def test_far_probe_is_one_shared_horizon_not_three_full_attempts(monkeypatch):
    calls = {"far": 0}

    class FakeDriver:
        def __init__(self, *_args):
            pass

        def begin_series(self):
            return True

        def end_series(self):
            return True

        @staticmethod
        def _ok(name):
            return bs.Scenario(name, status="ok")

        def negative_voluntary_walkoff(self):
            return self._ok("negative_voluntary_walkoff")

        def negative_off_point_kill(self):
            calls["far"] += 1
            return bs.Scenario(
                "negative_off_point_kill", detail="far horizon exhausted"
            )

        def negative_clean_capture(self):
            return self._ok("negative_clean_capture")

        def positive_kill_on_point(self):
            return self._ok("positive_kill_on_point")

        def negative_round_restart(self):
            return self._ok("negative_round_restart")

    monkeypatch.setattr(bs, "BreakDriver", FakeDriver)
    monkeypatch.setattr(bs.time, "sleep", lambda _seconds: None)

    results = bs.run_all(object(), object(), attempts=3)

    far = next(row for row in results
               if row["name"] == "negative_off_point_kill")
    assert calls["far"] == 1
    assert far["attempts"] == 1


def test_missing_disarm_ack_hard_stops_all_remaining_diagnostics(monkeypatch):
    calls = []

    class FakeDriver:
        def __init__(self, *_args):
            pass

        def begin_series(self):
            return True

        def end_series(self):
            return True

        @staticmethod
        def _ok(name):
            calls.append(name)
            return bs.Scenario(name, status="ok")

        def negative_voluntary_walkoff(self):
            return self._ok("negative_voluntary_walkoff")

        def negative_off_point_kill(self):
            calls.append("negative_off_point_kill")
            return bs.Scenario(
                "negative_off_point_kill",
                detail="kill poller disarm was not acknowledged",
                extra={"kill_disarm_ack": False},
            )

        def negative_clean_capture(self):
            return self._ok("negative_clean_capture")

        def positive_kill_on_point(self):
            return self._ok("positive_kill_on_point")

        def negative_round_restart(self):
            return self._ok("negative_round_restart")

    monkeypatch.setattr(bs, "BreakDriver", FakeDriver)
    monkeypatch.setattr(bs.time, "sleep", lambda _seconds: None)

    results = bs.run_all(object(), object(), attempts=3)

    assert calls == ["negative_off_point_kill"]
    assert [row["name"] for row in results] == calls
    assert results[-1]["kill_disarm_ack"] is False


def test_exact_successful_series_runs_the_required_synthetic_three_first(
        monkeypatch):
    calls = []

    class FakeDriver:
        def __init__(self, *_args):
            pass

        def begin_series(self):
            return True

        def end_series(self):
            return True

        @staticmethod
        def _ok(name):
            calls.append(name)
            return bs.Scenario(name, status="ok")

        def negative_off_point_kill(self):
            return self._ok("negative_off_point_kill")

        def positive_kill_on_point(self):
            return self._ok("positive_kill_on_point")

        def negative_round_restart(self):
            return self._ok("negative_round_restart")

        def negative_voluntary_walkoff(self):
            return self._ok("negative_voluntary_walkoff")

        def negative_clean_capture(self):
            return self._ok("negative_clean_capture")

    monkeypatch.setattr(bs, "BreakDriver", FakeDriver)
    results = bs.run_all(object(), object())

    assert tuple(calls[:3]) == bs.REQUIRED_SYNTHETIC_SCENARIOS
    required = [row for row in results
                if row["name"] in bs.REQUIRED_SYNTHETIC_SCENARIOS]
    assert len(required) == 3
    assert all(row["status"] == "ok" for row in required)


def test_lifecycle_abort_hard_stops_every_remaining_command(monkeypatch):
    calls = []

    class FakeDriver:
        def __init__(self, *_args):
            pass

        def begin_series(self):
            return True

        def end_series(self):
            return True

        def negative_off_point_kill(self):
            calls.append("negative_off_point_kill")
            return bs.Scenario(
                "negative_off_point_kill",
                detail="diagnostic series aborted: half_end",
                extra={"series_abort": "half_end", "series_abort_ack": True},
            )

        def positive_kill_on_point(self):
            calls.append("positive_kill_on_point")
            return bs.Scenario("positive_kill_on_point", status="ok")

        def negative_round_restart(self):
            calls.append("negative_round_restart")
            return bs.Scenario("negative_round_restart", status="ok")

        def negative_voluntary_walkoff(self):
            calls.append("negative_voluntary_walkoff")
            return bs.Scenario("negative_voluntary_walkoff", status="ok")

        def negative_clean_capture(self):
            calls.append("negative_clean_capture")
            return bs.Scenario("negative_clean_capture", status="ok")

    monkeypatch.setattr(bs, "BreakDriver", FakeDriver)
    results = bs.run_all(object(), object())

    assert calls == ["negative_off_point_kill"]
    assert len(results) == 1
    assert results[0]["series_abort"] == "half_end"


def test_missing_series_cleanup_ack_is_a_reported_hard_stop(monkeypatch):
    class FakeDriver:
        series_abort_reason = None
        series_abort_ack = None

        def __init__(self, *_args):
            pass

        def begin_series(self):
            return True

        def end_series(self):
            return False

        @staticmethod
        def _ok(name):
            return bs.Scenario(name, status="ok")

        def negative_off_point_kill(self):
            return self._ok("negative_off_point_kill")

        def positive_kill_on_point(self):
            return self._ok("positive_kill_on_point")

        def negative_round_restart(self):
            return self._ok("negative_round_restart")

        def negative_voluntary_walkoff(self):
            return self._ok("negative_voluntary_walkoff")

        def negative_clean_capture(self):
            return self._ok("negative_clean_capture")

    monkeypatch.setattr(bs, "BreakDriver", FakeDriver)

    results = bs.run_all(object(), object())

    assert results[-1] == {
        "name": "diagnostic_series_cleanup",
        "status": "not_staged",
        "detail": "diagnostic series cleanup was not acknowledged",
        "breaks_seen": 0,
        "series_abort": None,
        "series_abort_ack": None,
        "attempts": 1,
    }
