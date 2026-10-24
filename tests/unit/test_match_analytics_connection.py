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
    assert c["instruments"] == {"worst_share": "available", "shot_ping": "available", "session": "available",
                                "client_slice": "unavailable", "settings": "unavailable"}
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


# -- schema 34: the per-half client slice, with the settings the client declared --

CLIENTS = [
    {"player_id": "123", "half": "prelive", "ts": "2026-10-24 21:00:00", "span_s": "300", "pkts": "24000",
     "cmds": "72000", "drops": "0", "pps": "80.0", "cmds_pkt": "3.00", "msec_p50": "4", "msec_p95": "5",
     "msec_max": "9", "arr_p50": "12", "arr_p95": "13", "arr_max": "40", "interp_cap": "0",
     "interp_floor": "0", "stale_delta": "0"},
    {"player_id": "123", "half": "1", "ts": "2026-10-24 21:21:00", "span_s": "1206", "pkts": "100331",
     "cmds": "300993", "drops": "21", "pps": "83.2", "cmds_pkt": "3.00", "msec_p50": "4", "msec_p95": "5",
     "msec_max": "41", "arr_p50": "12", "arr_p95": "14", "arr_max": "388", "interp_cap": "0",
     "interp_floor": "3", "stale_delta": "2"},
    {"player_id": "123", "half": "2", "ts": "2026-10-24 21:45:00", "span_s": "1190", "pkts": "148000",
     "cmds": "296000", "drops": "4", "pps": "124.4", "cmds_pkt": "2.00", "msec_p50": "4", "msec_p95": "4",
     "msec_max": "12", "arr_p50": "8", "arr_p95": "9", "arr_max": "30", "interp_cap": "0",
     "interp_floor": "0", "stale_delta": "0"},
]
SETTINGS = [
    {"player_id": "123", "half": "1", "why": "start", "ts": "2026-10-24 21:00:03", "updaterate": "102",
     "cmdrate": "101", "rate": "100000", "interp": "0.01", "fps_max": "250", "lc": "1", "lw": "1"},
    # Changed cmdrate between halves: half 2 has no why=start row (the plugin logs start once per
    # match live), so the latest snapshot at or before the half-2 flush is the one that applies.
    {"player_id": "123", "half": "2", "why": "change", "ts": "2026-10-24 21:30:00", "updaterate": "102",
     "cmdrate": "125", "rate": "100000", "interp": "0.01", "fps_max": "250", "lc": "1", "lw": "1"},
    # A non-numeric answer landed NULL in the aggregator; it must stay null here.
    {"player_id": "109", "half": "1", "why": "start", "ts": "2026-10-24 21:00:04", "updaterate": "102",
     "cmdrate": "101", "rate": "NULL", "interp": "0.01", "fps_max": "99.5", "lc": "-1", "lw": "-1"},
]
SOURCES_34 = dict(SOURCES, net_clients=True, client_settings=True)


def test_halves_pair_each_slice_with_the_settings_declared_for_it():
    c = build_connection(INTERVALS, WORST, SESSIONS, SHOTS, PLAYERS, SOURCES_34, CLIENTS, SETTINGS)
    by = {p["player_name_at_match"]: p for p in c["players"]}
    halves = by["kroD-"]["halves"]
    # The warmup slice is not a half.
    assert [h["half"] for h in halves] == ["1", "2"]
    h1, h2 = halves
    assert (h1["pps"], h1["cmds_pkt"], h1["fps_est"]) == (83.2, 3.0, 250)
    assert h1["msec"] == {"p50": 4, "p95": 5, "max": 41} and h1["arr_ms"]["max"] == 388
    assert (h1["drops"], h1["interp_floor"], h1["stale_delta"]) == (21, 3, 2)
    assert h1["settings"]["why"] == "start" and h1["settings"]["cl_cmdrate"] == 101.0
    # Half 2 takes the mid-match change, and the observed cadence agrees with it.
    assert h2["settings"]["why"] == "change" and h2["settings"]["cl_cmdrate"] == 125.0
    assert h2["fps_est"] == 249 and h2["pps"] == 124.4
    # Nothing declared for this player: slices still publish, settings read null.
    assert by["nicholson"]["halves"] is None
    assert by["quiet"]["halves"] is None
    assert c["instruments"]["client_slice"] == "available" and c["instruments"]["settings"] == "available"


def test_a_non_numeric_answer_and_an_unsampled_lagcomp_read_null():
    row = dict(CLIENTS[1], player_id="109")
    c = build_connection(INTERVALS, WORST, SESSIONS, SHOTS, PLAYERS, SOURCES_34, [row], SETTINGS)
    by = {p["player_name_at_match"]: p for p in c["players"]}
    s = by["nicholson"]["halves"][0]["settings"]
    assert s["rate"] is None and s["fps_max"] == 99.5 and s["cl_lc"] == -1


def test_halves_say_why_they_are_missing_and_old_reports_are_untouched():
    c = build_connection(INTERVALS, WORST, SESSIONS, SHOTS, PLAYERS, SOURCES_34)
    assert c["instruments"]["client_slice"] == "not-recorded"   # tables exist, match predates the wave
    assert all(p["halves"] is None for p in c["players"])
    c = build_connection(INTERVALS, WORST, SESSIONS, SHOTS, PLAYERS, SOURCES)
    assert c["instruments"]["client_slice"] == "unavailable"    # tables absent
    assert c["instruments"]["settings"] == "unavailable"


def test_public_block_still_carries_no_half_and_no_setting():
    c = build_connection(INTERVALS, WORST, SESSIONS, SHOTS, PLAYERS, SOURCES_34, CLIENTS, SETTINGS)
    dto = _connection_block({"connection": c})
    assert_sanitized(dto)
    assert "players" not in dto
    assert dto["instruments"]["client_slice"] == "available"
    body = str(dto)
    for leaked in ("'halves'", "'cl_cmdrate'", "'fps_est'", "388", "125.0"):   # keys and values, not the prose that names them
        assert leaked not in body, leaked


# -- schema 35: minute slices roll up into the half --

def _minute(ts, span, pkts, cmds, drops, pps, p95, mmax, a95, amax, floor, sd):
    return dict(CLIENTS[1], half="1", ts=ts, span_s=span, pkts=pkts, cmds=cmds, drops=drops, pps=pps,
                cmds_pkt="3.00", msec_p50="4", msec_p95=p95, msec_max=mmax, arr_p50="12", arr_p95=a95,
                arr_max=amax, interp_floor=floor, interp_cap="0", stale_delta=sd)


MINUTES = [
    _minute("2026-10-24 21:01:00", "60", "5000", "15000", "1", "83.3", "5", "9", "13", "20", "0", "0"),
    _minute("2026-10-24 21:02:00", "60", "4800", "14400", "9", "80.0", "32", "72", "35", "77", "2", "1"),
    _minute("2026-10-24 21:02:40", "40", "3400", "10200", "0", "85.0", "5", "8", "13", "19", "0", "0"),
]


def test_minutes_sum_into_the_half_and_are_published_in_order():
    c = build_connection(INTERVALS, WORST, SESSIONS, SHOTS, PLAYERS, SOURCES_34, MINUTES, SETTINGS)
    h = {p["player_name_at_match"]: p for p in c["players"]}["kroD-"]["halves"][0]
    assert h["half"] == "1" and h["span_s"] == 160
    assert (h["drops"], h["interp_floor"], h["stale_delta"]) == (10, 2, 1)
    assert h["pps"] == round(13200 / 160, 3) and h["cmds_pkt"] == 3.0
    # The bad minute shows in max, not in the median ...
    assert h["msec"] == {"p50": 4, "p95": 5, "max": 72}
    assert h["arr_ms"]["max"] == 77
    # ... and the minute that carries it is findable.
    assert [m["ts"] for m in h["minutes"]] == ["2026-10-24 21:01:00", "2026-10-24 21:02:00", "2026-10-24 21:02:40"]
    assert h["minutes"][1]["msec"] == {"p50": 4, "p95": 32, "max": 72}
    assert h["settings"]["cl_cmdrate"] == 101.0


def test_a_single_row_half_reads_exactly_as_before():
    c = build_connection(INTERVALS, WORST, SESSIONS, SHOTS, PLAYERS, SOURCES_34, CLIENTS, SETTINGS)
    h1 = {p["player_name_at_match"]: p for p in c["players"]}["kroD-"]["halves"][0]
    assert (h1["pps"], h1["cmds_pkt"], h1["fps_est"], h1["minutes"], h1["span_s"]) == (83.2, 3.0, 250, None, 1206)
