"""`connection` block (schema 30): built from rows, published without ids.

The three instruments are kept apart on purpose. A worst-of share is relative to
the other players on the box; per-shot ping is exact but only exists where the
shot-detail stream was on; the engine session spans the whole connection. The
block must never fill one from another, and must read null -- not zero -- where
an instrument was not recording.
"""
from __future__ import annotations

from scripts.analytics_report_dto import _connection_block, assert_sanitized
from scripts.match_analytics import build_connection

PLAYERS = [
    {"player_id": 123, "player_name_at_match": "kroD-", "team": 1},
    {"player_id": 109, "player_name_at_match": "nicholson", "team": 1},
    {"player_id": 7, "player_name_at_match": "quiet", "team": 2},
]
INTERVALS = [{"windows": "221", "drops_per_window": "4.70", "jitter_worst_avg_ms": "83.5",
              "latency_worst_avg_ms": "168.0", "windows_ge300": "2", "lagcomp_off_windows": "0",
              "maxunlag_hits_per_window": "0.10", "choke_windows": "3"}]
WORST = [
    {"worst_name": "kroD-", "jitter_worst_windows": "177", "latency_worst_windows": "13",
     "drops_worst_windows": "103", "drops_when_worst": "618", "latency_spikes_ge300": "2",
     "jitter_when_worst_ms": "79.0", "latency_when_worst_max_ms": "381.0"},
    {"worst_name": "someone who left", "jitter_worst_windows": "4", "latency_worst_windows": "0",
     "drops_worst_windows": "0", "drops_when_worst": "0", "latency_spikes_ge300": "0",
     "jitter_when_worst_ms": "60.0", "latency_when_worst_max_ms": "NULL"},
]
SESSIONS = [
    {"player_id": "109", "session_seconds": "3249", "session_packets": "583612", "session_drops": "5",
     "session_latency_avg_ms": "27.9", "session_latency_max_ms": "203.1", "session_jitter_avg_ms": "5.1",
     "session_loss_avg_pct": "0", "session_loss_max_pct": "73"},
    {"player_id": "109", "session_seconds": "33", "session_packets": "1274", "session_drops": "6",
     "session_latency_avg_ms": "48.8", "session_latency_max_ms": "153.1", "session_jitter_avg_ms": "7.4",
     "session_loss_avg_pct": "0.1", "session_loss_max_pct": "1"},
]
SHOTS = [{"player_id": "123", "shots_with_ping": "148", "shot_ping_avg_ms": "37.0",
          "shot_ping_sd_ms": "7.0", "shot_ping_max_ms": "78", "shot_net_dropped": "0"}]
SOURCES = {"net_intervals": True, "net_sessions": True, "shot_ping": True}


def test_shares_are_per_window_and_missing_instruments_read_null():
    c = build_connection(INTERVALS, WORST, SESSIONS, SHOTS, PLAYERS, SOURCES)
    assert c["status"] == "available"
    assert c["match"]["windows"] == 221 and c["match"]["drops_per_window"] == 4.7
    by = {p["player_name_at_match"]: p for p in c["players"]}
    assert by["kroD-"]["worst_share"] == {"jitter": 0.801, "latency": 0.059, "drops": 0.466}
    assert by["kroD-"]["drops_when_worst"] == 618
    assert by["kroD-"]["shot_ping"]["avg_ms"] == 37.0 and by["kroD-"]["session"] is None
    assert by["nicholson"]["worst_share"] == {"jitter": 0.0, "latency": 0.0, "drops": 0.0}
    assert by["nicholson"]["shot_ping"] is None
    # Two sessions for one player: the longest one is the connection that played.
    assert by["nicholson"]["session"]["seconds"] == 3249
    assert by["nicholson"]["session"]["drop_rate_pct"] == 0.001
    assert by["quiet"]["session"] is None and by["quiet"]["shot_ping"] is None
    assert c["instruments"] == {"worst_share": "available", "shot_ping": "available", "session": "available"}
    # A worst-of name that is not on the roster is not invented into a player.
    assert "someone who left" not in by


def test_instruments_say_why_they_are_missing():
    c = build_connection(INTERVALS, WORST, [], [], PLAYERS,
                         {"net_intervals": True, "net_sessions": False, "shot_ping": True})
    assert c["instruments"]["session"] == "unavailable"   # table absent
    assert c["instruments"]["shot_ping"] == "not-recorded"  # column exists, stream was off
    none = build_connection([], [], [], [], PLAYERS, {"net_intervals": False})
    assert none["status"] == "unavailable" and none["players"] == [] and none["match"] is None
    empty = build_connection([{"windows": "0"}], [], [], [], PLAYERS, SOURCES)
    assert empty["status"] == "unavailable" and "no telemetry windows" in empty["reason"]


def test_public_block_is_the_box_only_and_passes_the_forbidden_scan():
    c = build_connection(INTERVALS, WORST, SESSIONS, SHOTS, PLAYERS, SOURCES)
    dto = _connection_block({"connection": c})
    assert_sanitized(dto)
    assert "players" not in dto
    assert dto["match"]["windows"] == 221 and dto["instruments"]["session"] == "available"
    body = str(dto)
    # instruments.worst_share names the instrument, which is fine; a player's VALUES are not.
    for leaked in ("kroD-", "nicholson", "0.801", "618", "27.9", "drops_when_worst", "shot_ping': {"):
        assert leaked not in body, leaked
    # The producer's own report still carries the rows: the private tier reads them there.
    assert [p["player_name_at_match"] for p in c["players"]] == ["kroD-", "nicholson", "quiet"]
    old = _connection_block({"schema_version": 29})
    assert old["status"] == "unavailable" and old["reason"] == "not-in-report"
