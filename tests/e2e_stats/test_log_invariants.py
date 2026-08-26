"""Tests for the log-level negative checks.

Every check here is asserted in both directions. A negative check that cannot
fire is worse than no check: it reports "0 violations" forever and reads like
evidence. Real Lane B captures come back clean, so the only way to know these
work is to feed them logs that should fail.

Line shapes are copied verbatim from real DoD 1.3 captures, including the `<0>`
authid the unpatched stack writes and the `<BOT>` the patched one does.
"""

from __future__ import annotations

from . import log_invariants as li

TS = "L 08/10/2026 - 04:18:12: "


def _kill(killer, kuid, kteam, victim, vuid, vteam, *, at="04:18:10", weapon="garand"):
    return (f"L 08/10/2026 - {at}: "
            f'"{killer}<{kuid}><BOT><{kteam}>" killed '
            f'"{victim}<{vuid}><BOT><{vteam}>" with "{weapon}"')


def _assist(assister, auid, ateam, victim, vuid, vteam, *, at="04:18:12"):
    return (f"L 08/10/2026 - {at}: "
            f'"{assister}<{auid}><BOT><{ateam}>" triggered "assist" against '
            f'"{victim}<{vuid}><BOT><{vteam}>" '
            f'(assister_position "-417 -329 -372") (victim_position "-733 751 -404")')


def _frag_context(killer, kuid, kteam, victim, vuid, vteam, *, headshot=0):
    return (TS + f'"{killer}<{kuid}><BOT><{kteam}>" triggered '
            f'"frag_context" against "{victim}<{vuid}><BOT><{vteam}>" '
            f'with "garand" (headshot "{headshot}")')


# -- the check parses real lines at all ------------------------------------


def test_real_line_shapes_are_recognised():
    """If the regexes silently matched nothing, every check below would pass
    vacuously. This is the guard against that."""
    log = "\n".join([
        _kill("Claire", 6, "Allies", "Wesker", 14, "Axis"),
        _assist("Mario", 13, "Allies", "Wesker", 14, "Axis"),
        TS + '"Claire<3><BOT><Allies>" triggered "cap_break" (flag "POINT_ANZIO_PLAZA") (position "-83 98 -418")',
    ])
    s = li.summarise(log)
    assert (s["kills"], s["assists"], s["breaks"]) == (1, 1, 1)


def test_the_unpatched_authid_shape_also_parses():
    """The stack logs `<0>` without the Lane B patch and `<BOT>` with it. A
    parser that only handled one would go blind on half the captures."""
    log = ('L 08/10/2026 - 03:31:25: "Lara<7><0><Allies>" killed '
           '"Sephiroth<8><0><Axis>" with "30cal"')
    assert li.summarise(log)["kills"] == 1


# -- killer must not be credited an assist on their own kill ---------------


def test_killer_credited_an_assist_is_caught():
    log = "\n".join([
        _kill("Claire", 6, "Allies", "Wesker", 14, "Axis"),
        _assist("Claire", 6, "Allies", "Wesker", 14, "Axis"),
    ])
    v = li.check_assist_attribution(log)
    assert len(v) == 1
    assert "own kill" in v[0]


def test_a_different_assister_is_fine():
    log = "\n".join([
        _kill("Claire", 6, "Allies", "Wesker", 14, "Axis"),
        _assist("Mario", 13, "Allies", "Wesker", 14, "Axis"),
    ])
    assert li.check_assist_attribution(log) == []


def test_the_same_player_killing_a_different_victim_is_fine():
    """Pairing is by victim, not by killer — otherwise any player who both
    killed someone and assisted on someone else would look like a violation."""
    log = "\n".join([
        _kill("Claire", 6, "Allies", "Bowser", 11, "Axis"),
        _assist("Claire", 6, "Allies", "Wesker", 14, "Axis"),
    ])
    assert li.check_assist_attribution(log) == []


def test_an_old_kill_outside_the_window_does_not_pair():
    """The same victim dies repeatedly over a match. Pairing an assist with a
    kill minutes earlier would invent violations out of ordinary play."""
    log = "\n".join([
        _kill("Claire", 6, "Allies", "Wesker", 14, "Axis", at="04:10:00"),
        _assist("Claire", 6, "Allies", "Wesker", 14, "Axis", at="04:18:12"),
    ])
    assert li.check_assist_attribution(log) == []


# -- team-mates must not be credited ---------------------------------------


def test_teammate_assist_is_caught():
    """Friendly fire damage must never produce an assist. This holds without
    any kill line, which matters because it is the check that still works when
    the pairing fails."""
    v = li.check_assist_attribution(_assist("Mario", 13, "Allies", "Fox", 1, "Allies"))
    assert len(v) == 1
    assert "SAME team" in v[0]


def test_cross_team_assist_is_fine():
    assert li.check_assist_attribution(
        _assist("Mario", 13, "Allies", "Wesker", 14, "Axis")) == []


def test_self_assist_is_caught():
    v = li.check_assist_attribution(_assist("Mario", 13, "Allies", "Mario", 13, "Allies"))
    assert len(v) == 1
    assert "self-assist" in v[0]


# -- cap_break attribution -------------------------------------------------


def test_break_by_a_spectator_is_caught():
    """A false-positive break silently inflates objective rating and nothing
    ever contradicts it, so the shapes that are wrong on their face are worth
    catching even though full validation needs zone state."""
    log = TS + '"Ghost<9><BOT><Spectator>" triggered "cap_break" (flag "POINT_ANZIO_PLAZA")'
    v = li.check_break_attribution(log)
    assert len(v) == 1
    assert "contesting" in v[0]


def test_break_with_no_team_is_caught():
    log = TS + '"Ghost<9><BOT><>" triggered "cap_break" (flag "POINT_ANZIO_PLAZA")'
    assert len(li.check_break_attribution(log)) == 1


def test_break_by_a_real_player_is_fine():
    log = TS + '"Claire<3><BOT><Allies>" triggered "cap_break" (flag "POINT_ANZIO_PLAZA")'
    assert li.check_break_attribution(log) == []


# -- real captures ---------------------------------------------------------


def test_a_clean_capture_produces_no_violations():
    """The positive control: ordinary play must not trip any of these, or the
    checks are unusable regardless of whether they can fire."""
    log = "\n".join([
        _kill("Sonic", 7, "Allies", "Bowser", 11, "Axis", at="06:57:41"),
        _kill("Claire", 6, "Allies", "Wesker", 14, "Axis", at="06:57:49"),
        _assist("Mario", 13, "Allies", "Wesker", 14, "Axis", at="06:57:50"),
        _kill("Pyramid", 9, "Axis", "Sonic", 7, "Allies", at="06:58:05"),
        _assist("Claire", 6, "Allies", "Seymour", 5, "Axis", at="06:58:05"),
    ])
    s = li.summarise(log)
    assert s["assist_violations"] == []
    assert s["break_violations"] == []
    assert (s["kills"], s["assists"]) == (3, 2)


def test_engine_kills_split_exactly_into_frags_teamkills_and_unknowns():
    log = "\n".join([
        _kill("A", 1, "Allies", "B", 2, "Axis"),
        _kill("A", 1, "Allies", "C", 3, "Allies"),
        _kill("A", 1, "allies", "D", 4, "Axis"),
        _kill("A", 1, "Allies", "A", 1, "Allies"),
    ])
    evidence = li.kill_classification(log)
    assert evidence["kills"] == 4
    assert evidence["frags"] == 1
    assert evidence["teamkills"] == 1
    assert evidence["unclassified"] == 2


def test_teamkill_frag_context_is_forbidden_and_not_counted_as_canonical():
    marker = _frag_context("A", 1, "Allies", "C", 3, "Allies", headshot=1)
    evidence = li.frag_context_classification(marker)
    assert evidence["total"] == 1
    assert evidence["frags"] == 0
    assert evidence["teamkills"] == 1
    assert evidence["headshots"] == 0
    assert len(evidence["violations"]) == 1
    assert "teamkill emitted frag_context" in evidence["violations"][0]
    assert li.breakdrive_synthetic_frag_diagnostics(marker) == []


def test_enemy_frag_context_is_canonical_and_headshot_is_counted():
    marker = _frag_context("A", 1, "Allies", "B", 2, "Axis", headshot=1)
    evidence = li.frag_context_classification(marker)
    assert evidence["frags"] == 1
    assert evidence["headshots"] == 1
    assert evidence["violations"] == []


def test_enemy_non_headshot_frag_context_is_canonical_without_a_violation():
    marker = _frag_context("A", 1, "Allies", "B", 2, "Axis", headshot=0)
    evidence = li.frag_context_classification(marker)
    assert evidence["frags"] == 1
    assert evidence["headshots"] == 0
    assert evidence["violations"] == []


def test_unknown_or_same_user_frag_context_fails_closed():
    for marker in (
        _frag_context("A", 1, "allies", "B", 2, "Axis"),
        _frag_context("A", 1, "Allies", "A", 1, "Allies"),
    ):
        evidence = li.frag_context_classification(marker)
        assert evidence["unclassified"] == 1
        assert evidence["frags"] == 0
        assert len(evidence["violations"]) == 1


# -- match window ----------------------------------------------------------
#
# The bound for "how many rows may carry this match id". Sampling a counter
# around the play window reported a context leak that did not exist: 37 rows
# were tagged and the sampled bound said 36, because kills land between the
# state machine going live and the sample being taken.

MATCH_START = ('L 08/10/2026 - 15:35:49: KTP_MATCH_START (matchid '
               '"1786376148-TEST") (map "dod_anzio") (half "1st")')
MATCH_MIRROR = ('L 08/10/2026 - 15:35:49: [KTPMatchHandler.amxx] KTP_MATCH_START '
                '(matchid "1786376148-TEST") (map "dod_anzio") (half "1st") '
                '[test-mode mirror]')
MATCH_END = ('L 08/10/2026 - 15:48:29: KTP_MATCH_END (matchid "1786376148-TEST") '
             '(map "dod_anzio") (status "test")')


def _k(at="15:40:00"):
    return _kill("A", 1, "Allies", "B", 2, "Axis", at=at)


def test_kills_are_split_around_the_markers():
    log = "\n".join([_k(), MATCH_START, _k(), _k(), MATCH_END, _k()])
    w = li.match_window(log)
    assert (w["before"], w["during"], w["after"]) == (1, 2, 1)
    assert w["found"] and w["ended"]


def test_the_test_mode_mirror_does_not_open_a_second_window():
    """The plugin logs KTP_MATCH_START twice — once real, once mirrored. Taking
    the later one would drop every kill in between from the bound."""
    log = "\n".join([MATCH_START, MATCH_MIRROR, _k(), _k(), MATCH_END])
    assert li.match_window(log)["during"] == 2


def test_no_match_reports_not_found_rather_than_zero_leak():
    """A run with no match must not read as 'nothing leaked' — there was
    nothing to leak into."""
    w = li.match_window("\n".join([_k(), _k()]))
    assert w["found"] is False
    assert w["during"] == 0


def test_an_unended_match_runs_to_the_end_of_the_log():
    """If end_match never fired, everything after the start is still inside the
    match as far as the daemon is concerned."""
    log = "\n".join([MATCH_START, _k(), _k()])
    w = li.match_window(log)
    assert w["during"] == 2 and w["after"] == 0 and w["ended"] is False


def test_periodic_markers_are_counted_only_inside_the_match():
    marker = '"Bot<1><BOT><Axis>" triggered "position_sample"'
    log = "\n".join([marker, MATCH_START, marker, marker, MATCH_END, marker])
    assert li.count_in_match(log, 'triggered "position_sample"') == 2


def test_statsme_replay_window_excludes_clean_and_next_match_flushes():
    weaponstats = '"Bot<1><BOT><Axis>" triggered "weaponstats"'
    next_start = MATCH_START.replace("1786376148-TEST", "1786377000-TEST")
    log = "\n".join([
        MATCH_START,
        weaponstats,
        MATCH_END,
        weaponstats,
        next_start,
        weaponstats,
    ])

    assert li.count_in_match(log, 'triggered "weaponstats"') == 1
    assert li.count_after_match(log, 'triggered "weaponstats"') == 1


def test_buffered_pre_interval_marker_is_not_diagnostic_match_evidence():
    buffered = (
        _frag_context("Denton", 2, "Allies", "Gruntilda", 9, "Axis")
        .replace('with "garand"', 'with "mortar"')
        + ' (matchid "-") (half "0") (event_epoch "100")'
    )
    valid = (
        _frag_context("Leon", 1, "Allies", "GLaDOS", 9, "Axis")
        + ' (matchid "1786376148-TEST") (half "1") '
          '(event_epoch "110")'
    )
    wrong_in_interval = (
        _frag_context("A", 3, "Allies", "B", 4, "Axis")
        + ' (matchid "other-TEST") (half "1") (event_epoch "111")'
    )
    foreign_pre_interval = (
        _frag_context("C", 5, "Allies", "D", 6, "Axis")
        + ' (matchid "previous-real-match") (half "1") '
          '(event_epoch "99")'
    )
    scope = li.producer_markers_for_match(
        "\n".join([
            MATCH_START, buffered, valid, wrong_in_interval,
            foreign_pre_interval, MATCH_END,
        ]),
        'triggered "frag_context"', match_id="1786376148-TEST", half=1,
        start_epoch=105, end_epoch=120,
    )

    assert scope["markers"] == [valid]
    assert scope["buffered_pre_interval"] == [buffered]
    assert scope["context_mismatches"] == [
        wrong_in_interval, foreign_pre_interval,
    ]


def test_post_match_flag_state_is_not_claimed_as_pipeline_loss():
    """The daemon intentionally drops ownership after match context closes."""
    marker = 'KTP_FLAG_STATE (map "dod_anzio") (flag_index "1")'
    log = "\n".join([marker, MATCH_START, marker, marker, MATCH_END, marker])
    assert li.count_in_match(log, "KTP_FLAG_STATE ") == 2


def test_marker_count_without_a_match_is_zero():
    marker = '"Bot<1><BOT><Axis>" triggered "position_sample"'
    assert li.count_in_match(marker, 'triggered "position_sample"') == 0


def test_only_successful_in_match_breakdrive_kills_expect_frag_diagnostics():
    successful = (
        TS + "[KTPBreakDrive.amxx] [BD] kill flag=3 capteam=2 mode=far "
        "victim=9 vname=GLaDOS killer=1 kname=Leon dist=1953 "
        "count_before=2 owner_before=0"
    )
    abort = TS + (
        "[KTPBreakDrive.amxx] [BD] kill ABORT flag=-1 mode=far "
        "no stageable capture while armed"
    )
    other_plugin = successful.replace("KTPBreakDrive.amxx", "NotBreakDrive.amxx")
    log = "\n".join([
        successful, MATCH_START, successful, abort, other_plugin, MATCH_END,
        successful,
    ])

    diagnostics = li.breakdrive_synthetic_frag_diagnostics(log)

    assert diagnostics == [successful]


def test_no_match_never_grants_a_synthetic_frag_exception():
    marker = TS + (
        "[KTPBreakDrive.amxx] [BD] kill flag=1 capteam=1 mode=near "
        "victim=2 vname=A killer=3 kname=B dist=4 count_before=2 "
        "owner_before=2"
    )
    assert li.breakdrive_synthetic_frag_diagnostics(marker) == []


def test_restart_queue_dispatch_expects_one_exact_frag_diagnostic():
    marker = (
        TS + "[KTPBreakDrive.amxx] [BD] restart_queue seq=4 flag=1 "
        "fname=POINT_BRIDGE capteam=1 victim=2 vname=Lara killer=7 "
        "killer_userid=41 kname=Master dist=238 count_before=2 "
        "count_queued=2 owner_before=0 restart_timer=1.00 "
        "round_before=702.50 drained=1"
    )
    log = "\n".join([MATCH_START, marker, MATCH_END])
    daemon = "\n".join([
        '"Master" <P:321,U:41,W:BOT:a,T:Axis>',
        '"Lara" <P:329,U:22,W:BOT:b,T:Allies>',
        "KTP_NO_ROW_MATCHED: frag_context: no row for killer=321 "
        "victim=329 weapon=amerknife",
    ])

    evidence = li.frag_context_diagnostic_evidence(log, daemon)

    assert evidence["expected_synthetic_unmatched"] == 1
    assert evidence["observed_unmatched"] == 1
    assert evidence["expected_identities"] == ["321->329:amerknife"]
    assert evidence["observed_identities"] == ["321->329:amerknife"]
    assert evidence["unresolved_expected"] == []


def test_frag_diagnostic_evidence_maps_identity_and_preserves_duplicates():
    synthetic = (
        TS + "[KTPBreakDrive.amxx] [BD] kill flag=1 capteam=2 mode=far "
        "victim=9 vname=GLaDOS killer=1 kname=Leon dist=1000 "
        "count_before=2 owner_before=1"
    )
    log = "\n".join([MATCH_START, synthetic, synthetic, MATCH_END])
    daemon = "\n".join([
        '2026-08-20 - E002: "Leon" <P:321,U:1,W:BOT:a,T:Allies> entered',
        '2026-08-20 - E002: "GLaDOS" <P:329,U:9,W:BOT:b,T:Axis> entered',
        "KTP_NO_ROW_MATCHED: frag_context: no row for killer=321 "
        "victim=329 weapon=amerknife -- diagnostic",
        "KTP_NO_ROW_MATCHED: frag_context: no row for killer=321 "
        "victim=329 weapon=amerknife -- diagnostic",
    ])

    evidence = li.frag_context_diagnostic_evidence(log, daemon)

    assert evidence["expected_synthetic_unmatched"] == 2
    assert evidence["observed_unmatched"] == 2
    assert evidence["expected_identities"] == ["321->329:amerknife"] * 2
    assert evidence["observed_identities"] == ["321->329:amerknife"] * 2
    assert evidence["unresolved_expected"] == []
    assert evidence["unparsed_observed"] == []


def test_pre_interval_warning_does_not_enter_diagnostic_identity_set():
    synthetic = (
        TS + "[KTPBreakDrive.amxx] [BD] kill flag=1 capteam=2 mode=far "
        "victim=9 vname=GLaDOS killer=1 kname=Leon dist=1000 "
        "count_before=2 owner_before=1"
    )
    buffered = (
        _frag_context("Denton", 2, "Allies", "Gruntilda", 9, "Axis")
        .replace('with "garand"', 'with "mortar"')
        + ' (matchid "-") (half "0") (event_epoch "100")'
    )
    log = "\n".join([MATCH_START, buffered, synthetic, MATCH_END])
    daemon = "\n".join([
        '"Leon" <P:321,U:1,W:BOT:a,T:Allies>',
        '"GLaDOS" <P:329,U:9,W:BOT:b,T:Axis>',
        '"Denton" <P:322,U:2,W:BOT:c,T:Allies>',
        '"Gruntilda" <P:330,U:10,W:BOT:d,T:Axis>',
        "KTP_NO_ROW_MATCHED: frag_context: no row for killer=322 "
        "victim=330 weapon=mortar",
        "KTP_NO_ROW_MATCHED: frag_context: no row for killer=321 "
        "victim=329 weapon=amerknife",
    ])

    evidence = li.frag_context_diagnostic_evidence(
        log, daemon, ignored_producer_markers=[buffered]
    )

    assert evidence["observed_identities"] == ["321->329:amerknife"]
    assert evidence["ignored_pre_interval_identities"] == ["322->330:mortar"]
    assert len(evidence["ignored_pre_interval_warnings"]) == 1


def test_pre_interval_identity_cannot_hide_expected_breakdrive_warning():
    synthetic = (
        TS + "[KTPBreakDrive.amxx] [BD] kill flag=1 capteam=2 mode=far "
        "victim=9 vname=GLaDOS killer=1 kname=Leon dist=1000 "
        "count_before=2 owner_before=1"
    )
    buffered = (
        _frag_context("Leon", 1, "Allies", "GLaDOS", 9, "Axis")
        .replace('with "garand"', 'with "amerknife"')
        .replace('(headshot "0")', '(headshot "0") (matchid "-") '
                 '(half "0") (event_epoch "100")')
    )
    daemon = "\n".join([
        '"Leon" <P:321,U:1,W:BOT:a,T:Allies>',
        '"GLaDOS" <P:329,U:9,W:BOT:b,T:Axis>',
        "KTP_NO_ROW_MATCHED: frag_context: no row for killer=321 "
        "victim=329 weapon=amerknife",
    ])

    evidence = li.frag_context_diagnostic_evidence(
        "\n".join([MATCH_START, buffered, synthetic, MATCH_END]), daemon,
        ignored_producer_markers=[buffered],
    )

    assert evidence["observed_identities"] == ["321->329:amerknife"]
    assert evidence["ignored_pre_interval_warnings"] == []


def test_frag_diagnostic_evidence_does_not_guess_ambiguous_names():
    synthetic = (
        TS + "[KTPBreakDrive.amxx] [BD] kill flag=1 capteam=2 mode=far "
        "victim=9 vname=Same killer=1 kname=Leon dist=1000 "
        "count_before=2 owner_before=1"
    )
    log = "\n".join([MATCH_START, synthetic, MATCH_END])
    daemon = "\n".join([
        '"Leon" <P:321,U:1,W:BOT:a,T:Allies>',
        '"Same" <P:329,U:9,W:BOT:b,T:Axis>',
        '"Same" <P:330,U:10,W:BOT:c,T:Axis>',
        "KTP_NO_ROW_MATCHED: frag_context: no row for killer=321 "
        "victim=329 weapon=amerknife",
    ])

    evidence = li.frag_context_diagnostic_evidence(log, daemon)

    assert evidence["expected_identities"] == []
    assert len(evidence["unresolved_expected"]) == 1
