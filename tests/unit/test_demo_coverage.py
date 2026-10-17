"""Regression tests for scripts/demo_coverage.py.

The whole measurement rests on one number read out of the demo's directory
entry, and the two ways to get that number wrong are silent: the playback
length is the SECOND entry (the first is the signon segment and is always 0.0,
so a reader that takes entry 0 reports every half as totally missing), and the
float sits at byte 76 of a 92-byte entry (a reader off by one field returns the
CD track or the frame count and calls it seconds).

Both are pinned here against a hand-built file whose bytes match a real HLTV
demo's layout -- 2 entries, times [0.0, 1257.4] -- as measured on
scrim_1783041573-ATL1_h2-2607022141-dod_armory_b6.dem, 2026-09-26.

The second group pins what replaced `loss`. That column anchored every demo at a
hardcoded game_time of 3.0 and reported the difference to the half end, which is
the head offset charged to the tail; it is refuted in KTPAMXX#160 and gone. The
tests here hold the three properties the replacement needs and the old column
could not have: the tail check shares no term with the game clock it vouches
for, `t0` is WITHHELD rather than guessed when the tail is not known complete,
and every demo failing the tail band at once refuses as a clock problem instead
of reporting a fleet of lost tails. The control at the end re-derives the old
column's answer from the same numbers, so the refutation is pinned rather than
only described in a docstring.
"""
from __future__ import annotations

import datetime as dt
import os
import struct
from zoneinfo import ZoneInfo

import pytest

from scripts.demo_coverage import (DEMO_STAMP_TZ, HALF_SECONDS, TAIL_BAND_SECONDS,
                                   Coverage, DemoFormatError, main, measure,
                                   parse_args, read_track_time, stamp_epoch)

EASTERN = ZoneInfo(DEMO_STAMP_TZ)
STAMP = "2609211930"          # 2026-09-21 19:30, the name build_demo writes
MATCH = "1789953053-CHI1"


def build_demo(tmp_path, track_times, magic=b"HLDEMO\0\0", closed_after=None):
    """A .dem with only the bytes this reader looks at: header, then directory.

    `closed_after` sets the mtime to the stamp plus that many seconds, which is
    the only way to exercise the tail check -- a freshly written temp file reads
    as a tail short by however long ago 2026-09-21 was.
    """
    body = b"\0" * 4096
    directory_offset = 544 + len(body)

    header = bytearray(544)
    header[0:8] = magic
    struct.pack_into("<ii", header, 8, 5, 48)          # demo protocol, net protocol
    header[16:16 + 12] = b"maps/dod_x\0\0"
    struct.pack_into("<i", header, 540, directory_offset)

    directory = bytearray(struct.pack("<i", len(track_times)))
    for i, seconds in enumerate(track_times):
        entry = bytearray(92)
        struct.pack_into("<i", entry, 0, i)             # type: 0 loading, 1 playback
        entry[4:4 + 8] = b"Playback"
        struct.pack_into("<i", entry, 72, 7)            # CD track -- next field over
        struct.pack_into("<f", entry, 76, seconds)
        struct.pack_into("<i", entry, 80, 12345)        # frame count -- next field back
        directory += entry

    path = tmp_path / f"ktp_{MATCH}_h2-{STAMP}-dod_anzio.dem"
    path.write_bytes(bytes(header) + body + bytes(directory))
    if closed_after is not None:
        when = stamp_epoch(STAMP, EASTERN) + closed_after
        os.utime(path, (when, when))
    return path


def test_reads_the_playback_entry_not_the_signon_segment(tmp_path):
    assert read_track_time(build_demo(tmp_path, [0.0, 1257.4])) == pytest.approx(1257.4, abs=0.1)


def test_rejects_a_file_that_is_not_a_demo(tmp_path):
    with pytest.raises(DemoFormatError):
        read_track_time(build_demo(tmp_path, [0.0, 1257.4], magic=b"NOTDEMO\0"))


# --- the name's stamp, which is the tail check's only clock ----------------------

def test_the_stamp_is_yymmddhhmm_in_the_recording_host_s_local_time():
    got = stamp_epoch("2609211930", EASTERN)
    assert got == dt.datetime(2026, 9, 21, 19, 30, tzinfo=EASTERN).timestamp()


def test_dst_is_resolved_per_date_so_winter_and_summer_both_decode():
    # A fixed offset is what makes half the year read as a lost tail. Both
    # stamps say 12:30 local; only a per-date offset puts them an hour apart in
    # UTC, so a single hardcoded offset fails this.
    winter = dt.datetime.fromtimestamp(stamp_epoch("2601151230", EASTERN), dt.timezone.utc)
    summer = dt.datetime.fromtimestamp(stamp_epoch("2607151230", EASTERN), dt.timezone.utc)
    assert (winter.hour, winter.minute) == (17, 30)     # EST, UTC-5
    assert (summer.hour, summer.minute) == (16, 30)     # EDT, UTC-4


def test_a_stamp_that_is_not_a_date_is_refused_rather_than_coerced():
    with pytest.raises(ValueError):
        stamp_epoch("9999999999", EASTERN)


# --- the tail check, and why it is a band ---------------------------------------

def _row(track_time, *, closed_after=None, engine_half_end=None, live=95.4):
    recorded = stamp_epoch(STAMP, EASTERN)
    return Coverage(MATCH, 2, "x.dem", track_time=track_time, live_game_time=live,
                    engine_half_end=engine_half_end, recorded_at=recorded,
                    closed_at=None if closed_after is None else recorded + closed_after)


def test_a_tail_inside_the_minute_band_is_complete():
    # The stamp resolves to a minute, so a complete tail lands anywhere in
    # [0,60) -- which is why this is a verdict and not a figure.
    for residual in (0.0, 33.0, 59.9):
        assert _row(1240.0, closed_after=1240.0 + residual).tail_verdict == "complete"


def test_a_sixty_second_lost_tail_lands_in_the_next_band():
    row = _row(1240.0, closed_after=1240.0 + TAIL_BAND_SECONDS + 5.0)
    assert row.tail_verdict == "short"
    assert row.tail_s == pytest.approx(TAIL_BAND_SECONDS + 5.0)


def test_a_file_closed_before_it_could_have_recorded_that_much_is_not_complete():
    assert _row(1240.0, closed_after=1200.0).tail_verdict == "early"


def test_the_tail_is_unknown_rather_than_complete_without_a_close_time():
    # A remote demo whose server sends no Last-Modified. Reporting "complete"
    # here would vouch for a tail using no evidence at all.
    assert _row(1240.0, closed_after=None).tail_verdict == "unknown"


def test_the_tail_check_shares_no_term_with_the_game_clock_it_licenses():
    # The whole point of the wall-clock test: move the engine half end by 500 s
    # and the tail verdict cannot notice. If it could, it would not be
    # independent evidence for t0.
    a = _row(1240.0, closed_after=1270.0, engine_half_end=1292.3)
    b = _row(1240.0, closed_after=1270.0, engine_half_end=1792.3)
    assert a.tail_s == b.tail_s
    assert a.tail_verdict == b.tail_verdict == "complete"


# --- t0 is derived, and withheld when it would be wrong -------------------------

def test_t0_is_the_half_end_minus_the_playback_length():
    # The measured shape: 38 of 48 official halves came back in [50,60).
    row = _row(1240.0, closed_after=1270.0, engine_half_end=1292.3)
    assert row.t0 == pytest.approx(52.3)


def test_t0_is_withheld_when_the_tail_is_not_known_complete():
    # THE GUARD. Against a short tail this subtraction reports the lost tail as
    # head offset and reads entirely plausible, which is how the old column
    # survived for weeks.
    short = _row(1240.0, closed_after=1240.0 + TAIL_BAND_SECONDS + 5.0, engine_half_end=1292.3)
    assert short.tail_verdict == "short"
    assert short.t0 is None
    assert short.head_margin is None
    # CONTROL: the same two numbers DO yield a t0 once the tail is vouched for,
    # so the None above is the guard firing and not a missing input.
    assert _row(1240.0, closed_after=1270.0, engine_half_end=1292.3).t0 is not None


def test_t0_is_unknown_rather_than_zero_when_the_half_has_no_end_at_all():
    recorded = stamp_epoch(STAMP, EASTERN)
    row = Coverage(MATCH, 2, "x.dem", track_time=1240.0, live_game_time=None,
                   recorded_at=recorded, closed_at=recorded + 1270.0)
    assert row.half_ends_at is None
    assert row.t0 is None


def test_a_negative_t0_is_reported_rather_than_clamped():
    # track_time past the engine end: the pause/overtime shape the 1200 s model
    # never described. Two of the 48 measured halves are this, at -143.9 and -64.4.
    row = _row(2486.6, closed_after=2500.0, engine_half_end=2342.7)
    assert row.t0 == pytest.approx(-143.9, abs=0.1)


# --- the head, which is what is actually missing --------------------------------

def test_head_margin_is_how_much_demo_sits_in_front_of_go_live():
    row = _row(1240.0, closed_after=1270.0, engine_half_end=1292.3, live=304.1)
    assert row.head_margin == pytest.approx(304.1 - 52.3)


def test_a_half_going_live_inside_the_head_offset_has_a_margin_at_or_below_zero():
    # Never observed on the measured population (min 55.2 s) and the exposure
    # worth a gate: a half live within t0 of the map change starts un-recorded.
    row = _row(1240.0, closed_after=1270.0, engine_half_end=1292.3, live=40.0)
    assert row.head_margin < 0


def test_a_producer_side_shift_of_context_live_moves_the_margin_and_not_t0():
    # context_live is written by stats_logging, not the engine. KTPMatchHandler
    # 0.10.176 moved it and the old column read that as a fleet-wide regression.
    early = _row(1240.0, closed_after=1270.0, engine_half_end=1292.3, live=95.4)
    late = _row(1240.0, closed_after=1270.0, engine_half_end=1292.3, live=105.4)
    assert early.t0 == late.t0
    assert late.head_margin - early.head_margin == pytest.approx(10.0)


# --- the engine round clock as the half end -------------------------------------

class FakeCli:
    """Answers the two queries measure() makes; records the SQL it was sent."""

    def __init__(self, live: str = "", clock: str = ""):
        self.live, self.clock, self.sent = live, clock, []

    def execute(self, sql: str) -> str:
        self.sent.append(sql)
        return self.clock if "round_time_left" in sql else self.live


def test_an_overtime_half_needs_no_half_length_override_when_the_clock_is_known():
    row = _row(1497.0, closed_after=1510.0, engine_half_end=1500.0)
    assert row.end_source == "clock"
    assert row.t0 == pytest.approx(3.0)


def test_a_half_without_a_clock_falls_back_to_the_assumed_end_and_says_so():
    row = _row(1289.4, closed_after=1300.0)
    assert row.end_source == "assumed"
    assert row.half_ends_at == pytest.approx(95.4 + HALF_SECONDS)


def test_measure_threads_the_assumed_half_length_into_every_row(tmp_path):
    # Without this the flag parses, prints in --help, and changes nothing.
    demo = build_demo(tmp_path, [0.0, 1257.4])
    rows = measure([demo], cli=None, half_seconds=900.0)
    assert [r.half_seconds for r in rows] == [900.0]


def test_measure_decodes_the_stamp_and_reads_the_close_time_off_the_file(tmp_path):
    demo = build_demo(tmp_path, [0.0, 1240.0], closed_after=1270.0)
    (row,) = measure([demo], cli=None)
    assert row.recorded_at == pytest.approx(stamp_epoch(STAMP, EASTERN))
    assert row.tail_verdict == "complete"
    assert row.tail_s == pytest.approx(30.0, abs=1.0)


def test_measure_takes_the_median_of_score_rows_over_flag_rows_and_context_live(tmp_path):
    demo = build_demo(tmp_path, [0.0, 1240.0], closed_after=1270.0)
    clock = "\n".join([
        f"score\t{MATCH}\t2\t1292.3",
        f"score\t{MATCH}\t2\t1292.4",
        f"score\t{MATCH}\t2\t1597.0",   # one late row must not drag the end
        f"flag\t{MATCH}\t2\t1100.0",    # flag rows are only the fallback
    ])
    cli = FakeCli(live=f"{MATCH}\t2\t105.4\n", clock=clock)
    (row,) = measure([demo], cli=cli)
    assert row.end_source == "clock"
    assert row.half_ends_at == pytest.approx(1292.4)
    assert row.live_game_time == pytest.approx(105.4)


def test_measure_uses_flag_state_rows_when_a_half_has_no_score_rows(tmp_path):
    demo = build_demo(tmp_path, [0.0, 1240.0], closed_after=1270.0)
    cli = FakeCli(live=f"{MATCH}\t2\t105.4\n", clock=f"flag\t{MATCH}\t2\t1292.0\n")
    (row,) = measure([demo], cli=cli)
    assert row.half_ends_at == pytest.approx(1292.0)


def test_measure_falls_back_to_context_live_when_no_clock_row_exists(tmp_path):
    demo = build_demo(tmp_path, [0.0, 1240.0], closed_after=1270.0)
    (row,) = measure([demo], cli=FakeCli(live=f"{MATCH}\t2\t95.4\n"))
    assert row.end_source == "assumed"
    assert row.half_ends_at == pytest.approx(95.4 + HALF_SECONDS)


def test_the_clock_query_drops_an_expired_clock_and_the_no_time_limit_sentinel(tmp_path):
    # round_time_left 0 is an award after expiry (reads late); -1 is "no time limit".
    demo = build_demo(tmp_path, [0.0, 1240.0])
    cli = FakeCli()
    measure([demo], cli=cli)
    clock_sql = [q for q in cli.sent if "round_time_left" in q]
    assert clock_sql and clock_sql[0].count("round_time_left > 0") == 2
    assert "is_initial = 0" in clock_sql[0]


# --- the two gates, and the refutation they replaced ----------------------------

def test_every_half_out_of_band_at_once_refuses_as_a_clock_problem(tmp_path, capsys):
    # The failure a wrong --demo-tz produces. Reporting it as lost tails is the
    # wrong headline, and an hour-sized offset moves every demo together.
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        build_demo(tmp_path / name, [0.0, 1240.0], closed_after=1240.0 + 3600.0)
    rc = main(["--no-database", "--demos",
               *[str(p) for p in sorted(tmp_path.glob("*/*.dem"))]])
    assert rc == 2
    assert "REFUSING" in capsys.readouterr().err


def test_one_short_tail_among_several_is_a_finding_and_not_a_refusal(tmp_path, capsys):
    # The discriminating case: the refusal above must not swallow a real loss.
    (tmp_path / "ok").mkdir()
    (tmp_path / "bad").mkdir()
    build_demo(tmp_path / "ok", [0.0, 1240.0], closed_after=1270.0)
    build_demo(tmp_path / "bad", [0.0, 1240.0], closed_after=1240.0 + 95.0)
    rc = main(["--no-database", "--demos",
               *[str(p) for p in sorted(tmp_path.glob("*/*.dem"))]])
    err = capsys.readouterr().err
    assert rc == 1
    assert "REFUSING" not in err
    assert "tail short" in err


def test_the_head_gap_gate_reads_the_margin_and_is_wired_to_the_flag(tmp_path):
    demo = build_demo(tmp_path, [0.0, 1240.0], closed_after=1270.0)
    cli = FakeCli(live=f"{MATCH}\t2\t40.0\n", clock=f"score\t{MATCH}\t2\t1292.3\n")
    (row,) = measure([demo], cli=cli)
    assert row.head_margin < 0
    assert parse_args(["--max-head-gap", "30"]).max_head_gap == 30.0


def test_max_loss_is_gone_rather_than_quietly_accepted():
    # It scored the head offset, so the gate could never express the question it
    # was pointed at. Pinned so a revert is a test failure and not a surprise.
    with pytest.raises(SystemExit):
        parse_args(["--max-loss", "5"])


def test_control_the_retired_column_still_reports_a_loss_on_a_complete_tail():
    # THE REFUTATION, pinned. 1240.0 s of playback against an engine end of
    # 1292.3 is a half whose tail is complete -- and the old anchor would have
    # called it 49.3 s short, which is the fleet-wide median it reported.
    row = _row(1240.0, closed_after=1270.0, engine_half_end=1292.3)
    assert row.tail_verdict == "complete"
    old_loss = row.half_ends_at - (3.0 + row.track_time)
    assert old_loss == pytest.approx(49.3)
    assert not hasattr(row, "loss")
