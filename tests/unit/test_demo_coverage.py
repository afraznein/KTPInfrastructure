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

The rest of this file pins the instrument that replaced two earlier wrong ones.
`loss` anchored every demo at a hardcoded game_time of 3.0 and charged the head
offset to the tail. The wall-clock tail BAND that replaced it could not fail at
all: it reduced to the demo name's own minute rounding. So the properties under
test are the ones neither of those had -- the tail test is structural and has a
positive case, `t0` shares no term with the half-end model, a half the gate
cannot judge FAILS instead of passing quietly, and each retired knob stays
retired. The controls re-derive the retired answers from the same numbers, so
the refutations are pinned rather than only described in a docstring.
"""
from __future__ import annotations

import os
import struct

import pytest

from scripts.demo_coverage import (BROADCAST_DELAY_SECONDS, HALF_SECONDS,
                                   MAX_EPOCH_FIT_SPREAD, Coverage, DemoFormatError,
                                   DemoTruncatedError, epoch_offsets, main, measure,
                                   parse_args, read_track_time)

MATCH = "1789953053-CHI1"
STAMP = "2609211930"


def build_demo(tmp_path, track_times, magic=b"HLDEMO\0\0", directory_offset=None,
               directory_bytes=None, name=None):
    """A .dem with only the bytes this reader looks at: header, then directory.

    `directory_offset` overrides the header field, which is how the truncated
    case is built: a recording killed before close never has its directory
    written, so the field stays 0.
    """
    body = b"\0" * 4096
    real_offset = 544 + len(body)

    header = bytearray(544)
    header[0:8] = magic
    struct.pack_into("<ii", header, 8, 5, 48)          # demo protocol, net protocol
    header[16:16 + 12] = b"maps/dod_x\0\0"
    struct.pack_into("<i", header, 540,
                     real_offset if directory_offset is None else directory_offset)

    if directory_bytes is None:
        directory = bytearray(struct.pack("<i", len(track_times)))
        for i, seconds in enumerate(track_times):
            entry = bytearray(92)
            struct.pack_into("<i", entry, 0, i)         # type: 0 loading, 1 playback
            entry[4:4 + 8] = b"Playback"
            struct.pack_into("<i", entry, 72, 7)        # CD track -- next field over
            struct.pack_into("<f", entry, 76, seconds)
            struct.pack_into("<i", entry, 80, 12345)    # frame count -- next field back
            directory += entry
        directory_bytes = bytes(directory)

    path = tmp_path / (name or f"ktp_{MATCH}_h2-{STAMP}-dod_anzio.dem")
    path.write_bytes(bytes(header) + body + directory_bytes)
    return path


def _row(track_time=1240.0, *, closed_at=1_790_000_000.0, epoch_offset=1_789_998_700.0,
         spread=1.0, live=95.4, engine_half_end=None, delay=BROADCAST_DELAY_SECONDS):
    """A Coverage whose terms are explicit; the arithmetic is pinned below."""
    return Coverage(MATCH, 2, "x.dem", track_time=track_time, live_game_time=live,
                    half_seconds=HALF_SECONDS, engine_half_end=engine_half_end,
                    closed_at=closed_at, epoch_offset=epoch_offset,
                    epoch_offset_spread=spread, broadcast_delay=delay)


# --- the directory entry, which every other number depends on -------------------

def test_reads_the_playback_entry_not_the_signon_segment(tmp_path):
    assert read_track_time(build_demo(tmp_path, [0.0, 1257.4])) == pytest.approx(1257.4, abs=0.1)


def test_rejects_a_file_that_is_not_a_demo(tmp_path):
    with pytest.raises(DemoFormatError):
        read_track_time(build_demo(tmp_path, [0.0, 1257.4], magic=b"NOTDEMO\0"))


# --- the tail test, which is structural and has a positive case -----------------

def test_a_recording_killed_before_close_has_no_directory_and_is_truncated(tmp_path):
    # THE POSITIVE CASE. nDirectoryOffset is written by DemoFile::Close(), so a
    # killed recording leaves it at 0 -- the shape of every genuine tail loss in
    # the corpus.
    with pytest.raises(DemoTruncatedError):
        read_track_time(build_demo(tmp_path, [0.0, 1240.0], directory_offset=0))


def test_a_directory_that_claims_more_entries_than_it_holds_is_truncated(tmp_path):
    demo = build_demo(tmp_path, [], directory_bytes=struct.pack("<i", 4) + b"\0" * 40)
    with pytest.raises(DemoTruncatedError):
        read_track_time(demo)


def test_a_file_that_was_never_a_demo_is_not_a_tail_finding(tmp_path):
    # THE DISCRIMINATION, and the reason DemoTruncatedError exists. Collapsing
    # these two is how the real tail losses spent months as a skipped stderr
    # line: one is a demo that lost its tail, the other is not a demo.
    with pytest.raises(DemoFormatError) as caught:
        read_track_time(build_demo(tmp_path, [0.0, 1240.0], magic=b"NOTDEMO\0"))
    assert not isinstance(caught.value, DemoTruncatedError)


def test_a_truncated_demo_is_a_row_and_a_finding_rather_than_a_dropped_line(tmp_path):
    demo = build_demo(tmp_path, [0.0, 1240.0], directory_offset=0)
    (row,) = measure([demo], cli=None)
    assert row.track_time is None
    assert row.tail_verdict == "truncated"
    assert row.unmeasured_reason == "no directory"
    assert main(["--no-database", "--demos", str(demo)]) == 1


def test_a_demo_closed_with_its_directory_is_complete(tmp_path):
    (row,) = measure([build_demo(tmp_path, [0.0, 1240.0])], cli=None)
    assert row.tail_verdict == "complete"
    assert row.track_time == pytest.approx(1240.0, abs=0.1)


def test_control_the_retired_tail_band_could_not_have_seen_a_killed_recording():
    # THE REFUTATION, pinned as arithmetic. The band was
    #   tail_s = (close - stamp) - track
    # and killing a recording early moves `close` and `track` by the SAME amount,
    # so the quantity does not budge. It had no positive case because it could
    # not have one.
    stamp, close, track = 1_789_998_700.0, 1_790_000_000.0, 1240.0
    intact = (close - stamp) - track
    killed = ((close - 300.0) - stamp) - (track - 300.0)
    assert intact == killed
    # And it is gone, along with the clock it needed.
    assert not hasattr(_row(), "tail_s")
    with pytest.raises(SystemExit):
        parse_args(["--demo-tz", "UTC"])


# --- t0, fitted from two clocks and sharing no term with the half-end model -----

def test_t0_is_the_first_write_carried_back_by_the_broadcast_delay():
    # closed_at - track_time is the wall moment of the first write; the offset
    # maps wall to game time and the delay carries it to the frame's own time.
    row = _row(track_time=1240.0, closed_at=1_790_000_000.0,
               epoch_offset=1_789_998_700.0, delay=60.0)
    assert row.t0 == pytest.approx(1_790_000_000.0 - 1240.0 - 1_789_998_700.0 - 60.0)
    assert row.t0 == pytest.approx(0.0)


def test_t0_does_not_move_when_the_half_end_model_moves():
    # THE DIFFERENCE from the retired derivation, which was half_end - track_time
    # and therefore inherited every error in the half-end model -- including the
    # gap between the engine half end and the changelevel that stops the demo.
    near = _row(engine_half_end=1292.3)
    far = _row(engine_half_end=1792.3)
    assert near.t0 == far.t0
    # CONTROL: the half end still differs, so the equality above is t0 ignoring
    # it rather than the two rows being identical.
    assert near.half_ends_at != far.half_ends_at


def test_t0_needs_no_engine_clock_at_all():
    # Coverage the retired derivation could not give: a half whose producer
    # predates round_time_left has no engine end, and the fit does not care.
    row = _row(engine_half_end=None, live=None)
    assert row.half_ends_at is None
    assert row.t0 is not None


def test_t0_is_withheld_when_the_two_clocks_diverge():
    # A tech pause freezes game time while the wall clock runs, so the offset
    # steps mid-half and averaging over the step is a wrong t0 that reads fine.
    paused = _row(spread=MAX_EPOCH_FIT_SPREAD + 0.1)
    assert paused.t0 is None
    assert paused.head_margin is None
    assert "diverge" in paused.unmeasured_reason
    # CONTROL: the same row inside the spread DOES yield a t0, so the None above
    # is the guard firing and not a missing input.
    assert _row(spread=MAX_EPOCH_FIT_SPREAD - 0.1).t0 is not None


def test_t0_is_withheld_without_a_close_time_and_says_which_term_is_missing():
    # A remote demo whose server sends no Last-Modified.
    row = _row(closed_at=None)
    assert row.t0 is None
    assert row.unmeasured_reason == "no close time"


def test_t0_is_withheld_when_the_half_has_no_event_rows():
    row = _row(epoch_offset=None, spread=None)
    assert row.t0 is None
    assert row.unmeasured_reason == "no event rows"


def test_a_negative_t0_means_the_recording_predates_the_level_and_is_reported():
    # Not an error and not clamped: the recording began before this level
    # loaded, so the half is covered outright.
    row = _row(track_time=2500.0)
    assert row.t0 < 0
    assert row.head_margin > 0


# --- the head margin and the gate -----------------------------------------------

def test_head_margin_is_how_much_demo_sits_in_front_of_go_live():
    row = _row(live=304.1)
    assert row.head_margin == pytest.approx(304.1 - row.t0)


def test_a_half_going_live_inside_the_head_offset_has_a_margin_at_or_below_zero():
    # The exposure worth a gate: a half live within a delay's worth of the map
    # change starts un-recorded, and nothing else anywhere reports it.
    assert _row(track_time=1140.0, live=40.0).head_margin < 0


def test_a_producer_side_shift_of_context_live_moves_the_margin_and_not_t0():
    # context_live is written by stats_logging, not the engine. KTPMatchHandler
    # 0.10.176 moved it and the retired column read that as a fleet regression.
    early, late = _row(live=95.4), _row(live=105.4)
    assert early.t0 == late.t0
    assert late.head_margin - early.head_margin == pytest.approx(10.0)


def test_the_head_gap_gate_reads_the_margin_and_is_wired_to_the_flag(tmp_path):
    demo = build_demo(tmp_path, [0.0, 1240.0])
    offset = _offset_for(demo, 1240.0, wanted_margin=20.0)
    cli = FakeCli(live=f"{MATCH}\t2\t40.0\n", offsets=f"{MATCH}\t2\t{offset}\t1.0\n")
    (row,) = measure([demo], cli=cli)
    assert row.head_margin == pytest.approx(20.0, abs=0.5)
    assert parse_args(["--max-head-gap", "30"]).max_head_gap == 30.0


def test_an_unjudged_half_fails_the_gate_rather_than_passing_quietly(tmp_path, capsys):
    # THE NEW GUARD. The retired band stayed invisible because the halves it
    # could not evaluate produced no row and no exit code -- absence read as a
    # pass. A gate that silently skips what it cannot judge is the same defect.
    demo = build_demo(tmp_path, [0.0, 1240.0])
    rc = main(["--no-database", "--demos", str(demo), "--max-head-gap", "30"])
    assert rc == 1
    assert "could not be judged" in capsys.readouterr().err


def test_allow_unmeasured_is_the_deliberate_way_to_accept_them(tmp_path):
    # CONTROL for the test above: the failure is the unjudged half and nothing
    # else, so the opt-out turns it green without changing any measurement.
    demo = build_demo(tmp_path, [0.0, 1240.0])
    assert main(["--no-database", "--demos", str(demo),
                 "--max-head-gap", "30", "--allow-unmeasured"]) == 0


def test_the_report_names_every_half_it_could_not_judge(tmp_path, capsys):
    demo = build_demo(tmp_path, [0.0, 1240.0])
    main(["--no-database", "--demos", str(demo)])
    out = capsys.readouterr().out
    assert "no head margin on 1 of 1 halves" in out
    assert "no event rows" in out


# --- the SQL the fit depends on -------------------------------------------------

def _offset_for(demo, track_time, wanted_margin, live=40.0, delay=BROADCAST_DELAY_SECONDS):
    """The epoch_offset that puts head_margin at `wanted_margin` for this file."""
    return os.stat(demo).st_mtime - track_time - delay - (live - wanted_margin)


class FakeCli:
    """Answers the three queries measure() makes; records the SQL it was sent."""

    def __init__(self, live: str = "", clock: str = "", offsets: str = ""):
        self.live, self.clock, self.offsets, self.sent = live, clock, offsets, []

    def execute(self, sql: str) -> str:
        self.sent.append(sql)
        if "event_epoch" in sql:
            return self.offsets
        if "round_time_left" in sql:
            return self.clock
        return self.live


def test_the_offset_is_fitted_in_a_window_at_the_start_of_the_half():
    # The window is what keeps the fit ahead of any pause. Without the join it
    # would average across every step in the half and nothing would say so.
    cli = FakeCli()
    epoch_offsets(cli, [MATCH])
    (sql,) = cli.sent
    assert "MIN(game_time) AS g0" in sql
    assert "e.game_time <= b.g0 +" in sql


def test_the_offset_estimator_is_the_max_and_the_spread_is_the_range():
    # event_epoch is whole seconds against a sub-second game_time, so the offset
    # approaches its true value from BELOW -- a mean would sit half a second low
    # and the range is what the divergence control reads.
    cli = FakeCli()
    epoch_offsets(cli, [MATCH])
    (sql,) = cli.sent
    assert "MAX(e.event_epoch - e.game_time)" in sql
    assert "MIN(e.event_epoch - e.game_time)" in sql
    assert "AVG(" not in sql


def test_measure_threads_the_fitted_offset_and_spread_into_every_row(tmp_path):
    # Without this the query runs, the columns print, and t0 is never withheld.
    demo = build_demo(tmp_path, [0.0, 1240.0])
    cli = FakeCli(offsets=f"{MATCH}\t2\t1789998700.0\t7.5\n")
    (row,) = measure([demo], cli=cli)
    assert row.epoch_offset == pytest.approx(1_789_998_700.0)
    assert row.epoch_offset_spread == pytest.approx(7.5)
    assert row.t0 is None and "diverge" in row.unmeasured_reason


def test_measure_threads_the_broadcast_delay_into_every_row(tmp_path):
    rows = measure([build_demo(tmp_path, [0.0, 1240.0])], cli=None, broadcast_delay=30.0)
    assert [r.broadcast_delay for r in rows] == [30.0]


def test_the_delay_is_a_named_parameter_and_not_a_buried_constant():
    assert parse_args(["--broadcast-delay", "45"]).broadcast_delay == 45.0
    assert parse_args([]).broadcast_delay == BROADCAST_DELAY_SECONDS


# --- the engine round clock, now reported rather than load-bearing --------------

def test_the_clock_query_drops_an_expired_clock_and_the_no_time_limit_sentinel(tmp_path):
    # round_time_left 0 is an award after expiry (reads late); -1 is "no time limit".
    cli = FakeCli()
    measure([build_demo(tmp_path, [0.0, 1240.0])], cli=cli)
    clock_sql = [q for q in cli.sent if "round_time_left" in q]
    assert clock_sql and clock_sql[0].count("round_time_left > 0") == 2
    assert "is_initial = 0" in clock_sql[0]


def test_measure_takes_the_median_of_score_rows_over_flag_rows(tmp_path):
    clock = "\n".join([
        f"score\t{MATCH}\t2\t1292.3",
        f"score\t{MATCH}\t2\t1292.4",
        f"score\t{MATCH}\t2\t1597.0",   # one late row must not drag the end
        f"flag\t{MATCH}\t2\t1100.0",    # flag rows are only the fallback
    ])
    cli = FakeCli(live=f"{MATCH}\t2\t105.4\n", clock=clock)
    (row,) = measure([build_demo(tmp_path, [0.0, 1240.0])], cli=cli)
    assert row.end_source == "clock"
    assert row.half_ends_at == pytest.approx(1292.4)


def test_a_half_without_a_clock_falls_back_to_the_assumed_end_and_says_so(tmp_path):
    cli = FakeCli(live=f"{MATCH}\t2\t95.4\n")
    (row,) = measure([build_demo(tmp_path, [0.0, 1240.0])], cli=cli)
    assert row.end_source == "assumed"
    assert row.half_ends_at == pytest.approx(95.4 + HALF_SECONDS)


def test_measure_threads_the_assumed_half_length_into_every_row(tmp_path):
    rows = measure([build_demo(tmp_path, [0.0, 1257.4])], cli=None, half_seconds=900.0)
    assert [r.half_seconds for r in rows] == [900.0]


# --- what stays retired ---------------------------------------------------------

def test_max_loss_is_gone_rather_than_quietly_accepted():
    # It scored the head offset, so the gate could never express the question it
    # was pointed at. Pinned so a revert is a test failure and not a surprise.
    with pytest.raises(SystemExit):
        parse_args(["--max-loss", "5"])


def test_control_the_retired_column_still_reports_a_loss_on_a_complete_tail():
    # 1240.0 s of playback against an engine end of 1292.3 is a half whose tail
    # is complete -- and the old anchor would have called it 49.3 s short, which
    # is the fleet-wide median it reported.
    row = _row(track_time=1240.0, engine_half_end=1292.3)
    assert row.tail_verdict == "complete"
    assert row.half_ends_at - (3.0 + row.track_time) == pytest.approx(49.3)
    assert not hasattr(row, "loss")
