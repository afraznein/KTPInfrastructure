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
"""
from __future__ import annotations

import struct

import pytest

from scripts.demo_coverage import (DEMO_T0_GAME_TIME, HALF_SECONDS, Coverage,
                                   DemoFormatError, read_track_time)


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
