"""Unit tests for the GoldSrc SPLITPACKET reassembly in tests/smoke/rcon.py.

No sockets, no hlds — feeds synthetic datagrams straight into
_SplitReassembler. The 2-fragment golden case mirrors the live packet
captured 2026-07-10 (a `changelevel` rcon response on the 2.7.21 stack
crossed the ~1400-byte routeable limit and the client, then without
reassembly, raised "response missing 0xFFFFFFFF prefix").

Wire layout under test:
  int32 -2 (\\xfe\\xff\\xff\\xff) | int32 sequence id | byte (num << 4 | total)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from smoke.rcon import RconError, _SplitReassembler  # noqa: E402


def _print_packet(text: str) -> bytes:
    return b"\xff\xff\xff\xffl" + text.encode() + b"\x00"


def _fragment(seq: int, num: int, total: int, payload: bytes) -> bytes:
    return (
        b"\xfe\xff\xff\xff"
        + seq.to_bytes(4, "little")
        + bytes([(num << 4) | total])
        + payload
    )


def test_plain_packet_passthrough():
    r = _SplitReassembler()
    assert r.ingest(_print_packet("hello")) == "hello"
    assert not r.pending


def test_two_fragment_reassembly_in_order():
    whole = _print_packet("A" * 100 + "B" * 100)
    r = _SplitReassembler()
    assert r.ingest(_fragment(4, 0, 2, whole[:120])) is None
    assert r.pending
    assert r.ingest(_fragment(4, 1, 2, whole[120:])) == "A" * 100 + "B" * 100
    assert not r.pending


def test_fragments_out_of_order():
    whole = _print_packet("first-half|second-half")
    r = _SplitReassembler()
    assert r.ingest(_fragment(7, 1, 2, whole[15:])) is None
    assert r.ingest(_fragment(7, 0, 2, whole[:15])) == "first-half|second-half"


def test_interleaved_sequences_do_not_cross_contaminate():
    a = _print_packet("aaaa")
    b = _print_packet("bbbb")
    r = _SplitReassembler()
    assert r.ingest(_fragment(1, 0, 2, a[:5])) is None
    assert r.ingest(_fragment(2, 0, 2, b[:5])) is None
    assert r.ingest(_fragment(1, 1, 2, a[5:])) == "aaaa"
    assert r.ingest(_fragment(2, 1, 2, b[5:])) == "bbbb"
    assert not r.pending


def test_incomplete_split_reports_pending():
    r = _SplitReassembler()
    assert r.ingest(_fragment(9, 0, 3, b"x")) is None
    assert r.pending
    assert "seq=9: 1/3" in r.describe()


def test_bad_counters_rejected():
    r = _SplitReassembler()
    with pytest.raises(RconError, match="bad counters"):
        r.ingest(_fragment(1, 2, 2, b"x"))  # num >= total
    with pytest.raises(RconError, match="bad counters"):
        r.ingest(b"\xfe\xff\xff\xff" + (1).to_bytes(4, "little") + bytes([0x00]) + b"x")


def test_truncated_split_header_rejected():
    r = _SplitReassembler()
    with pytest.raises(RconError, match="too short"):
        r.ingest(b"\xfe\xff\xff\xff\x01\x00")


def test_total_mismatch_rejected():
    r = _SplitReassembler()
    r.ingest(_fragment(5, 0, 2, b"x"))
    with pytest.raises(RconError, match="total mismatch"):
        r.ingest(_fragment(5, 1, 3, b"y"))


def test_golden_live_shape_2026_07_10():
    """Mirror of the captured failure: fragment 0 of 2, seq id 4, payload
    beginning with the inner \\xff\\xff\\xff\\xffl print header."""
    inner = _print_packet("L 07/10/2026 - 10:29:32: Loading map \"dod_anzio\"\n" * 30)
    r = _SplitReassembler()
    frag0 = _fragment(4, 0, 2, inner[:1000])
    frag1 = _fragment(4, 1, 2, inner[1000:])
    assert frag0.startswith(b"\xfe\xff\xff\xff\x04\x00\x00\x00\x02")
    assert r.ingest(frag0) is None
    out = r.ingest(frag1)
    assert out is not None and out.count("Loading map") == 30
