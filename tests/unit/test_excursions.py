"""Excursions: solo runs behind the enemy's lines, from positions alone."""
from __future__ import annotations

from scripts.excursions import (ISOLATION_BY_MAP, ExcursionConfig,
                                build_excursions)

# A straight map: Allies spawn at y=-2400, Axis at y=+2400, five flags on the line.
FLAGS = [
    {"flag_index": 0, "flag_name": "allied_hq", "origin_x": 0, "origin_y": -2000},
    {"flag_index": 1, "flag_name": "allied_2nd", "origin_x": 0, "origin_y": -1000},
    {"flag_index": 2, "flag_name": "mid", "origin_x": 0, "origin_y": 0},
    {"flag_index": 3, "flag_name": "axis_2nd", "origin_x": 0, "origin_y": 1000},
    {"flag_index": 4, "flag_name": "axis_hq", "origin_x": 0, "origin_y": 2000},
]
ALLIES = (1, 2, 3)
AXIS = (4, 5, 6)


def spawns(half=1):
    rows = []
    for pid in ALLIES:
        rows += [{"half": half, "player_id": pid, "team": 1, "game_time": 0.0, "boundary_kind": "start"}] * 1
    for pid in AXIS:
        rows += [{"half": half, "player_id": pid, "team": 2, "game_time": 0.0, "boundary_kind": "start"}] * 1
    # three spawns per side are needed for a centroid: repeat with later times
    for t in (100.0, 200.0):
        for pid in ALLIES:
            rows.append({"half": half, "player_id": pid, "team": 1, "game_time": t, "boundary_kind": "start"})
        for pid in AXIS:
            rows.append({"half": half, "player_id": pid, "team": 2, "game_time": t, "boundary_kind": "start"})
    return rows


def samples(track, half=1):
    """track: {pid: [(t, x, y)]} -> position rows, alive."""
    rows = []
    for pid, pts in track.items():
        for t, x, y in pts:
            rows.append({"half": half, "player_id": pid, "team": 1 if pid in ALLIES else 2,
                         "game_time": t, "pos_x": x, "pos_y": y, "is_alive": 1})
    return rows


def base_tracks():
    # Everyone sits near their own spawn at t 0/100/200 so the centroids resolve,
    # and near mid for the rest of the half.
    tr = {}
    for pid in ALLIES:
        tr[pid] = [(0, 0, -2400), (100, 0, -2400), (200, 0, -2400)] + [(t, 50 * pid, -200) for t in range(300, 400, 2)]
    for pid in AXIS:
        tr[pid] = [(0, 0, 2400), (100, 0, 2400), (200, 0, 2400)] + [(t, 50 * pid, 200) for t in range(300, 400, 2)]
    return tr


def run(tracks, flag_states=None, cfg=None, map_name=None):
    return build_excursions(samples(tracks), FLAGS, spawns(), flag_states or [], cfg,
                            map_name=map_name)


def test_solo_deep_run_is_an_excursion_with_closest_flag():
    tr = base_tracks()
    # Player 1 leaves mid at 300 and walks to the axis HQ, alone, until 360.
    tr[1] = tr[1][:3] + [(t, 0, 200 + (t - 300) * 40) for t in range(300, 362, 2)]
    out = run(tr)
    assert out["status"] == "available"
    rows = out["rows"]
    assert len(rows) == 1
    r = rows[0]
    assert r["player_id"] == 1 and r["team"] == 1 and r["half"] == 1
    assert r["duration"] >= 20
    assert r["rear_flags"] == ["axis_hq", "axis_2nd"]
    assert r["closest_flag"] == "axis_hq" and r["closest_flag_distance"] < 500
    assert r["min_teammate_distance"] > 1200
    assert out["halves"]["1"]["rear_flags"] == {"allies": ["axis_hq", "axis_2nd"], "axis": ["allied_hq", "allied_2nd"]}


def test_a_teammate_alongside_is_not_an_excursion():
    tr = base_tracks()
    for pid in (1, 2):
        tr[pid] = tr[pid][:3] + [(t, 50 * pid, 200 + (t - 300) * 40) for t in range(300, 362, 2)]
    assert run(tr)["rows"] == []


def test_short_run_is_ignored_and_flags_we_own_are_not_targets():
    tr = base_tracks()
    tr[1] = tr[1][:3] + [(t, 0, 1400) for t in range(300, 308, 2)]  # 6 s only
    assert run(tr)["rows"] == []
    tr[1] = tr[1][:3] + [(t, 0, 1400 + (t - 300) * 10) for t in range(300, 340, 2)]
    owned = [{"half": 1, "flag_name": "axis_2nd", "owner_team": 1, "is_initial": 0, "game_time": 250.0}]
    r = run(tr, owned)["rows"][0]
    assert r["closest_flag"] == "axis_hq"  # axis_2nd is ours, so the HQ is the only target


def test_unavailable_without_positions_or_flags():
    assert build_excursions([], FLAGS, spawns(), [])["status"] == "unavailable"
    assert build_excursions(samples(base_tracks()), [], spawns(), [])["status"] == "unavailable"
    assert build_excursions(samples(base_tracks()), FLAGS, spawns(), [], source_available=False)["status"] == "unavailable"


def test_isolation_is_configurable():
    tr = base_tracks()
    tr[1] = tr[1][:3] + [(t, 0, 200 + (t - 300) * 40) for t in range(300, 362, 2)]
    tr[2] = tr[2][:3] + [(t, 900, 200 + (t - 300) * 40) for t in range(300, 362, 2)]  # 900 u beside
    assert run(tr)["rows"] == []
    assert len(run(tr, cfg=ExcursionConfig(isolation_units=800))["rows"]) == 2


def beside(distance):
    """Two players walking the same line, `distance` apart, deep in enemy ground."""
    tr = base_tracks()
    tr[1] = tr[1][:3] + [(t, 0, 200 + (t - 300) * 40) for t in range(300, 362, 2)]
    tr[2] = (tr[2][:3]
             + [(t, distance, 200 + (t - 300) * 40) for t in range(300, 362, 2)])
    return tr


def test_a_tight_map_keeps_a_run_the_flat_rule_dropped():
    # 1170 units apart. The flat 1200 calls that "standing near someone" and
    # drops the run; on lennon5, where p80 is 1145, it is genuinely alone.
    # This is the +13% direction on the most-played map in the pool.
    tr = beside(1170)
    assert run(tr)["rows"] == []                           # no map: flat 1200 fallback
    assert len(run(tr, map_name="dod_lennon5_b1")["rows"]) == 2


def test_a_wide_map_drops_a_run_the_flat_rule_kept():
    # The other direction: 1800 units reads as isolated under the flat rule,
    # but on railroad2 (p80 2292) that is still beside a teammate -- which is
    # why the flat rule over-reported there by more than half.
    tr = beside(1800)
    assert len(run(tr)["rows"]) == 2
    assert run(tr, map_name="dod_railroad2_s9a")["rows"] == []


def test_an_unmeasured_map_falls_back_to_the_league_wide_distance():
    out = run(beside(1300), map_name="dod_some_new_map_b2")
    assert len(out["rows"]) == 2
    assert out["parameters"]["isolation_units_applied"] == 1200.0
    assert "league-wide fallback" in out["caveats"][0]


def test_an_explicit_distance_still_overrides_the_table():
    # The sweep tooling pins one distance across every map to compare them.
    out = run(beside(1300), cfg=ExcursionConfig(isolation_units=900),
              map_name="dod_lennon5_b1")
    assert len(out["rows"]) == 2
    assert out["parameters"]["isolation_units_applied"] == 900.0


def test_the_applied_distance_is_reported():
    out = run(base_tracks(), map_name="dod_harrington")
    assert out["parameters"]["isolation_units_applied"] == ISOLATION_BY_MAP["dod_harrington"]
    assert "p80 measured for dod_harrington" in out["caveats"][0]


def credit(pid, flag, t, half=1):
    return {"half": half, "player_id": pid, "flag_name": flag, "game_time": t}


def test_a_rear_touch_is_measured_even_when_no_window_forms():
    # Player 1 pushes in WITH player 2, then finishes alone: no 10 s window,
    # but the touch itself is out ahead of the team (the reported case).
    tr = base_tracks()
    tr[1] = tr[1][:3] + [(t, 0, 200 + (t - 300) * 40) for t in range(300, 362, 2)]
    tr[2] = (tr[2][:3] + [(t, 150, 200 + (t - 300) * 40) for t in range(300, 354, 2)]
             + [(t, 150, 800) for t in range(354, 362, 2)])
    out = build_excursions(samples(tr), FLAGS, spawns(), [], None,
                           capture_credits=[credit(1, "axis_hq", 360.0)])
    assert out["rows"] == []  # a teammate stayed inside 1200 for the run
    touch = out["touches"][0]
    assert touch["player_id"] == 1 and touch["flag"] == "axis_hq"
    assert touch["teammate_gap"] > 1200
    assert touch["depth"] > 0.9 and touch["depth_gain"] > 0


def test_touches_ignore_flags_that_are_not_the_enemy_rear():
    tr = base_tracks()
    tr[1] = tr[1][:3] + [(t, 0, 200 + (t - 300) * 40) for t in range(300, 362, 2)]
    out = build_excursions(samples(tr), FLAGS, spawns(), [], None,
                           capture_credits=[credit(1, "mid", 360.0), credit(1, "axis_hq", 360.0)])
    assert [t["flag"] for t in out["touches"]] == ["axis_hq"]


def test_touches_are_empty_without_capture_credits():
    assert run(base_tracks())["touches"] == []
