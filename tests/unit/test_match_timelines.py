from __future__ import annotations

from scripts.match_timelines import TimelineConfig, build_shadow_timelines


def frag(event_id, at, killer, victim, killer_team, victim_team, half=1):
    return {
        "event_id": event_id, "event_unix": at, "event_time": f"t{at}",
        "half": half, "killer_id": killer, "killer_steam_id": f"S{killer}",
        "killer_name": f"P{killer}", "killer_team": killer_team,
        "victim_id": victim, "victim_steam_id": f"S{victim}",
        "victim_name": f"P{victim}", "victim_team": victim_team,
        "weapon": "garand", "headshot": 0,
    }


def test_shadow_timelines_detect_multikill_trade_opening_and_conversion():
    frags = [
        frag(1, 100, 1, 7, 1, 2),
        frag(2, 104, 1, 8, 1, 2),
        frag(3, 107, 9, 1, 2, 1),
        frag(4, 109, 2, 9, 1, 2),
    ]
    objectives = [{
        "event_unix": 112, "event_time": "t112", "half": 1,
        "team": 1, "team_name": "Allies", "flag_name": "middle",
    }]

    report = build_shadow_timelines(frags, objectives)

    assert report["privacy"] == "private_shadow_only"
    assert report["writes"] is False
    assert report["rating_impact"] is False
    assert report["opening_duels"][0]["winner"]["player_id"] == 1
    sequence = report["fast_multikills"][0]
    assert sequence["classification"] == "fast_2k"
    assert sequence["objective_conversion"] == {
        "converted": True, "seconds_after": 8.0, "event_time": "t112",
        "team": 1, "team_name": "Allies", "flag_name": "middle",
    }
    assert [row["trader"]["player_id"] for row in report["trades"]] == [9, 2]
    pair = next(row for row in report["head_to_head"]
                if row["player_a"]["player_id"] == 1
                and row["player_b"]["player_id"] == 9)
    assert (pair["a_kills"], pair["b_kills"]) == (0, 1)


def test_window_values_are_configurable_and_reported():
    config = TimelineConfig(
        multikill_seconds=3, trade_seconds=1,
        objective_conversion_seconds=4,
    )
    report = build_shadow_timelines([
        frag(1, 100, 1, 7, 1, 2), frag(2, 104, 1, 8, 1, 2),
    ], [], config)
    assert report["config"] == {
        "multikill_seconds": 3, "trade_seconds": 1,
        "objective_conversion_seconds": 4,
    }
    assert report["fast_multikills"] == []


def test_replay_suppresses_timed_inferences_but_keeps_ordered_facts():
    report = build_shadow_timelines([
        frag(1, 100, 1, 7, 1, 2), frag(2, 102, 1, 8, 1, 2),
    ], [], temporal_valid=False)
    assert report["status"] == "timed_metrics_suppressed"
    assert report["fast_multikills"] == []
    assert report["trades"] == []
    assert len(report["opening_duels"]) == 1
    assert len(report["head_to_head"]) == 2


def test_invalid_window_is_rejected():
    try:
        build_shadow_timelines([], [], TimelineConfig(trade_seconds=0))
    except ValueError as exc:
        assert "trade_seconds" in str(exc)
    else:
        raise AssertionError("zero window accepted")
