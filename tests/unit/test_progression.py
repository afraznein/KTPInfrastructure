"""Progression: cumulative per-player series per half, and its public form."""
from __future__ import annotations

import json

from scripts import analytics_report_dto as dto
from scripts.progression import build_progression

ROSTER = [
    {"player_id": 1, "player_name_at_match": "alpha", "team": 1},
    {"player_id": 2, "player_name_at_match": "bravo", "team": 1},
    {"player_id": 3, "player_name_at_match": "charlie", "team": 2},
]


def frag(t, killer, victim, killer_team, victim_team, half=1, game_time=True):
    row = {"half": half, "killer_id": killer, "victim_id": victim,
           "killer_team": killer_team, "victim_team": victim_team}
    if game_time:
        row["game_time"] = t
    return row


def hit(t, attacker, victim, amount, half=1):
    return {"half": half, "game_time": t, "attacker_id": attacker, "victim_id": victim,
            "attacker_team": 1 if attacker in (1, 2) else 2,
            "victim_team": 1 if victim in (1, 2) else 2, "damage_capped": amount}


def break_(t, breaker, half=1):
    return {"half": half, "game_time": t, "breaker_id": breaker}


def cap(t, player, half=1):
    return {"half": half, "game_time": t, "player_id": player}


def flag_event(t, flag_index, owner, half=1):
    return {"half": half, "game_time": t, "kind": "flag", "flag_index": flag_index,
            "owner": owner, "p_allies_after": 0.5, "delta": 0.1}


def series(block, pid, half, metric):
    for row in block["players"]:
        if (row["player_id"], row["half"], row["metric"]) == (pid, half, metric):
            return row["points"]
    raise AssertionError(f"no series for {pid}/{half}/{metric}")


def test_kills_and_deaths_are_running_totals_from_zero_per_half():
    frags = [
        frag(10, 1, 3, 1, 2),
        frag(25, 1, 3, 1, 2),
        frag(40, 3, 1, 2, 1),
        frag(5, 3, 2, 2, 1, half=2),
    ]
    block = build_progression(frags, None, None, ROSTER, damage_available=False, flags_available=False)
    assert block["status"] == "available"
    assert series(block, 1, 1, "kills") == [[0, 0], [10, 1], [25, 2]]
    assert series(block, 1, 1, "deaths") == [[0, 0], [40, 1]]
    assert series(block, 3, 1, "kills") == [[0, 0], [40, 1]]
    # Half 2 restarts the clock and the count.
    assert series(block, 3, 2, "kills") == [[0, 0], [5, 1]]
    assert series(block, 1, 2, "kills") == [[0, 0]]


def test_team_kills_and_suicides_do_not_count_as_kills_but_do_count_as_deaths():
    frags = [frag(10, 1, 2, 1, 1), frag(20, 3, 3, 2, 2)]
    block = build_progression(frags, None, None, ROSTER, damage_available=False, flags_available=False)
    assert series(block, 1, 1, "kills") == [[0, 0]]
    assert series(block, 2, 1, "deaths") == [[0, 0], [10, 1]]
    assert series(block, 3, 1, "kills") == [[0, 0]]
    assert series(block, 3, 1, "deaths") == [[0, 0], [20, 1]]


def test_events_without_a_clock_are_skipped_and_counted_in_coverage():
    frags = [frag(10, 1, 3, 1, 2), frag(None, 1, 3, 1, 2, game_time=False)]
    block = build_progression(frags, None, None, ROSTER, damage_available=False, flags_available=False)
    assert series(block, 1, 1, "kills") == [[0, 0], [10, 1]]
    assert block["coverage"] == {"frags_with_clock": 1, "frags_total": 2,
                                 "damage_with_clock": 0, "damage_total": 0,
                                 "cap_breaks_with_clock": 0, "cap_breaks_total": 0,
                                 "cap_participation_with_clock": 0,
                                 "cap_participation_total": 0}


def test_damage_accumulates_cross_team_only_and_same_tick_collapses():
    hits = [hit(3, 1, 3, 40), hit(3, 1, 3, 25), hit(9, 1, 2, 30), hit(12, 3, 1, 60)]
    block = build_progression([], hits, None, ROSTER, frags_available=False, flags_available=False)
    assert block["available"]["damage"] is True
    assert block["available"]["kills"] is False
    assert series(block, 1, 1, "damage") == [[0, 0], [3, 65]]
    assert series(block, 3, 1, "damage") == [[0, 0], [12, 60]]


def test_cap_breaks_are_running_totals_from_zero_per_half():
    breaks = [break_(15, 1), break_(45, 1), break_(20, 3, half=2)]
    block = build_progression([], None, None, ROSTER, cap_break_rows=breaks,
                              frags_available=False, damage_available=False,
                              flags_available=False)
    assert block["available"]["cap_breaks"] is True
    assert series(block, 1, 1, "cap_breaks") == [[0, 0], [15, 1], [45, 2]]
    assert series(block, 3, 2, "cap_breaks") == [[0, 0], [20, 1]]
    assert block["coverage"]["cap_breaks_with_clock"] == 3
    assert block["coverage"]["cap_breaks_total"] == 3


def test_cap_breaks_absent_reads_unavailable_not_zero():
    block = build_progression([frag(10, 1, 3, 1, 2)], None, None, ROSTER,
                              damage_available=False, flags_available=False)
    assert block["available"]["cap_breaks"] is False
    assert all(row["metric"] != "cap_breaks" for row in block["players"])


def test_cap_participation_are_running_totals_from_zero_per_half():
    caps = [cap(60, 2), cap(90, 2), cap(40, 3, half=2)]
    block = build_progression([], None, None, ROSTER, cap_participation_rows=caps,
                              frags_available=False, damage_available=False,
                              flags_available=False)
    assert block["available"]["cap_participation"] is True
    assert series(block, 2, 1, "cap_participation") == [[0, 0], [60, 1], [90, 2]]
    assert series(block, 3, 2, "cap_participation") == [[0, 0], [40, 1]]
    assert block["coverage"]["cap_participation_with_clock"] == 3
    assert block["coverage"]["cap_participation_total"] == 3


def test_cap_participation_absent_reads_unavailable_not_zero():
    block = build_progression([frag(10, 1, 3, 1, 2)], None, None, ROSTER,
                              damage_available=False, flags_available=False)
    assert block["available"]["cap_participation"] is False
    assert all(row["metric"] != "cap_participation" for row in block["players"])


def test_flag_differential_starts_from_spawn_ownership_and_mirrors_for_team_2():
    events = [flag_event(30, 2, 1), flag_event(50, 3, 1), flag_event(70, 1, 2)]
    seed = {0: 1, 1: 1, 2: 0, 3: 2, 4: 2}  # 2 - 2 = 0 at kickoff
    block = build_progression([], None, events, ROSTER, spawn_ownership=seed,
                              frags_available=False, damage_available=False)
    team1 = [r for r in block["teams"] if r["team"] == 1][0]["points"]
    team2 = [r for r in block["teams"] if r["team"] == 2][0]["points"]
    # Flag 3 flips from team 2 to team 1: one fewer for them, one more for us.
    assert team1 == [[0, 0], [30, 1], [50, 3], [70, 1]]
    assert team2 == [[0, 0], [30, -1], [50, -3], [70, -1]]


def test_replay_source_suppresses_everything():
    block = build_progression([frag(10, 1, 3, 1, 2)], None, None, ROSTER, temporal_valid=False)
    assert block["status"] == "timed_metrics_suppressed"
    assert block["players"] == []


def test_nothing_captured_reads_unavailable_not_zero():
    block = build_progression([], None, None, ROSTER)
    assert block["status"] == "unavailable"
    assert block["players"] == []


def test_public_block_carries_names_only_and_sanitizes():
    frags = [frag(10, 1, 3, 1, 2)]
    events = [flag_event(30, 2, 1)]
    private = build_progression(frags, None, events, ROSTER, spawn_ownership={0: 1},
                                damage_available=False)
    names = {p["player_id"]: p["player_name_at_match"] for p in ROSTER}
    public = dto._progression_block({"progression": private}, names)
    assert public["status"] == "available"
    assert {r["name"] for r in public["players"]} == {"alpha", "bravo", "charlie"}
    assert public["players"][0]["points"][0] == [0, 0]
    body = json.dumps(public)
    for bad in ("player_id", "steam_id", "timeline", "unix"):
        assert bad not in body
    dto.assert_sanitized({"progression": public})


def test_box_score_scale_scopes_over_all_players_and_flips_lower_is_better():
    players = [
        {"name": "alpha", "team": 1, "kills": 10, "deaths": 4, "kd_ratio": None},
        {"name": "bravo", "team": 1, "kills": 10, "deaths": 9, "kd_ratio": 1.5},
        {"name": "charlie", "team": 2, "kills": 3, "deaths": 4, "kd_ratio": 0.5},
    ]
    scale = dto._box_score_scale(players)
    assert scale["scope"] == "all_players"
    kills = scale["fields"]["kills"]
    assert kills == {"max_in_match": 10, "higher_is_better": True, "best": ["alpha", "bravo"]}
    deaths = scale["fields"]["deaths"]
    # The bar still scales on the max; the star goes to the minimum, ties kept.
    assert deaths == {"max_in_match": 9, "higher_is_better": False, "best": ["alpha", "charlie"]}
    assert scale["fields"]["kd_ratio"]["best"] == ["bravo"]
    # A field nobody has a value for is null, not zero.
    assert scale["fields"]["assists"] == {"max_in_match": None, "higher_is_better": True, "best": []}


def test_sanitized_report_carries_both_new_blocks():
    from tests.unit.test_analytics_report_dto import internal_report
    out = dto.sanitize_report(internal_report())
    assert out["contract_version"] == "analytics-report-dto-v1.10.0"
    assert out["progression"]["status"] == "unavailable"
    assert out["box_score_scale"]["fields"]["kills"]["max_in_match"] == 3
    assert out["box_score_scale"]["fields"]["kills"]["best"] == ["A"]
