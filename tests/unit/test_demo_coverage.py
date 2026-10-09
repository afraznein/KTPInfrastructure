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

The second group pins the OTHER half of `loss`, which is not the demo at all:
the producer-written context_live row and the assumed half length. Both move
`loss` on their own, so a shift in either reads as demo regression -- the trap
the module docstring now names.
"""
from __future__ import annotations

import struct

import pytest

from scripts.demo_coverage import (DEMO_T0_GAME_TIME, HALF_SECONDS, Coverage,
                                   DemoFormatError, measure, read_track_time)


def build_demo(tmp_path, track_times, magic=b"HLDEMO\0\0"):
    """A .dem with only the bytes this reader looks at: header, then directory."""
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

    path = tmp_path / "ktp_1789953053-CHI1_h2-2609211930-dod_anzio.dem"
    path.write_bytes(bytes(header) + body + bytes(directory))
    return path


def test_reads_the_playback_entry_not_the_signon_segment(tmp_path):
    assert read_track_time(build_demo(tmp_path, [0.0, 1257.4])) == pytest.approx(1257.4, abs=0.1)


def test_rejects_a_file_that_is_not_a_demo(tmp_path):
    with pytest.raises(DemoFormatError):
        read_track_time(build_demo(tmp_path, [0.0, 1257.4], magic=b"NOTDEMO\0"))


def test_loss_is_the_half_clock_the_demo_never_reached():
    # The worked case: 1789953053-CHI1 h2 went live at game_time 95.4, so the
    # half's clock ends at 1295.4; the demo covered to 1292.4.
    row = Coverage("1789953053-CHI1", 2, "x.dem", track_time=1289.4, live_game_time=95.4)
    assert row.covers_to == pytest.approx(1289.4 + DEMO_T0_GAME_TIME)
    assert row.half_ends_at == pytest.approx(95.4 + HALF_SECONDS)
    assert row.loss == pytest.approx(3.0)


def test_loss_is_unknown_rather_than_zero_when_the_half_never_went_live():
    row = Coverage("1789953053-CHI1", 2, "x.dem", track_time=1289.4, live_game_time=None)
    assert row.loss is None


def test_a_producer_side_shift_of_the_half_clock_moves_loss_with_the_demo_unchanged():
    # The trap this measurement carries: context_live is written by stats_logging,
    # not by the engine, so a producer change that moves it is reported as demo
    # loss. Same track_time, reference 10 s later, loss 10 s worse.
    early = Coverage("1789953053-CHI1", 2, "x.dem", track_time=1289.4, live_game_time=95.4)
    late = Coverage("1789953053-CHI1", 2, "x.dem", track_time=1289.4, live_game_time=105.4)
    assert early.covers_to == late.covers_to
    assert late.loss - early.loss == pytest.approx(10.0)


def test_the_assumed_half_length_is_part_of_loss_and_can_be_overridden():
    # An overtime or short half measured against the default reports a loss that
    # is wrong by the difference, which is why --half-seconds exists.
    default = Coverage("1789953053-CHI1", 2, "x.dem", track_time=1289.4, live_game_time=95.4)
    overtime = Coverage("1789953053-CHI1", 2, "x.dem", track_time=1289.4,
                        live_game_time=95.4, half_seconds=HALF_SECONDS + 300.0)
    assert default.half_seconds == HALF_SECONDS
    assert overtime.loss - default.loss == pytest.approx(300.0)


def test_measure_threads_the_assumed_half_length_into_every_row(tmp_path):
    # Without this the flag parses, prints in --help, and changes nothing.
    demo = build_demo(tmp_path, [0.0, 1257.4])
    rows = measure([demo], cli=None, half_seconds=900.0)
    assert [r.half_seconds for r in rows] == [900.0]


# --- the engine round clock as the half end -------------------------------------

class FakeCli:
    """Answers the two queries measure() makes; records the SQL it was sent."""

    def __init__(self, live: str = "", clock: str = ""):
        self.live, self.clock, self.sent = live, clock, []

    def execute(self, sql: str) -> str:
        self.sent.append(sql)
        return self.clock if "round_time_left" in sql else self.live


MATCH = "1789953053-CHI1"


def test_the_engine_clock_is_the_half_end_and_a_context_live_shift_does_not_move_loss():
    # The 0.10.176 artifact: context_live 10 s later, demo and engine clock unchanged.
    early = Coverage(MATCH, 2, "x.dem", track_time=1240.0, live_game_time=95.4, engine_half_end=1292.3)
    late = Coverage(MATCH, 2, "x.dem", track_time=1240.0, live_game_time=105.4, engine_half_end=1292.3)
    assert early.end_source == late.end_source == "clock"
    assert early.half_ends_at == late.half_ends_at == pytest.approx(1292.3)
    assert late.loss == early.loss == pytest.approx(1292.3 - (1240.0 + DEMO_T0_GAME_TIME))


def test_an_overtime_half_needs_no_half_length_override_when_the_clock_is_known():
    row = Coverage(MATCH, 3, "x.dem", track_time=1497.0, live_game_time=95.4, engine_half_end=1500.0)
    assert row.loss == pytest.approx(0.0)


def test_a_half_without_a_clock_falls_back_to_the_assumed_end_and_says_so():
    row = Coverage(MATCH, 2, "x.dem", track_time=1289.4, live_game_time=95.4)
    assert row.end_source == "assumed"
    assert row.half_ends_at == pytest.approx(95.4 + HALF_SECONDS)


def test_measure_takes_the_median_of_score_rows_over_flag_rows_and_context_live(tmp_path):
    demo = build_demo(tmp_path, [0.0, 1240.0])  # ..._h2-...: match 1789953053-CHI1 half 2
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
    demo = build_demo(tmp_path, [0.0, 1240.0])
    cli = FakeCli(live=f"{MATCH}\t2\t105.4\n", clock=f"flag\t{MATCH}\t2\t1292.0\n")
    (row,) = measure([demo], cli=cli)
    assert row.half_ends_at == pytest.approx(1292.0)


def test_measure_falls_back_to_context_live_when_no_clock_row_exists(tmp_path):
    demo = build_demo(tmp_path, [0.0, 1240.0])
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
