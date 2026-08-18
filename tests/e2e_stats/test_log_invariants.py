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


def test_marker_count_without_a_match_is_zero():
    marker = '"Bot<1><BOT><Axis>" triggered "position_sample"'
    assert li.count_in_match(marker, 'triggered "position_sample"') == 0
