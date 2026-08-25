import json
from pathlib import Path

import pytest

from scripts.lane_b_match_report import (
    _associate_damage_to_deaths,
    build_facts,
    generate_lane_b_report,
    summary_for_lane,
)


def _facts() -> dict:
    players = []
    frags = []
    for player_id in range(1, 13):
        team = 1 if player_id <= 6 else 2
        victim = player_id + 6 if team == 1 else player_id - 6
        players.append({
            "player_id": player_id,
            "player_name_at_match": f"Bot {player_id}",
            "team_name": f"Team {team}",
            "kills": 1,
            "deaths": 1,
            "assists": 0,
            "opponent_damage": 100,
            "team_kills": 0,
            "suicides": 0,
            "observed_seconds": 360,
        })
        frags.append({
            "event_id": f"frag-{player_id}", "half": 1,
            "time": 20 + player_id, "killer_id": player_id,
            "victim_id": victim, "killer_team": team,
            "victim_team": 2 if team == 1 else 1,
            "victim_life_id": f"h1-p{victim}-frag-{player_id}",
        })
    empty_components = {
        "mid_defense_points": 0, "aggression_points": 0,
        "enemy_flag_hold_points": 0, "active_flag_defense_points": 0,
        "sequence_continuity_points": 0, "position_points": 0,
    }
    return {
        "schema_version": 1,
        "match": {"match_id": "lane-b-unit-TEST", "map_name": "dod_anzio",
                  "duration_seconds": 360, "source_mode": "lane_b_ephemeral_mysql"},
        "players": players, "frags": frags, "damage_events": [],
        "death_resets": [], "captures": [], "cap_breaks": [],
        "position_points": {str(pid): 0 for pid in range(1, 13)},
        "position_components": {str(pid): dict(empty_components)
                                for pid in range(1, 13)},
        "momentum_points": {str(pid): 0 for pid in range(1, 13)},
        "momentum_summary": {
            "status": "experimental_shadow", "team1": 1, "team2": 2,
            "ownership_coverage_percent": 100.0,
            "curve": [{"half": 1, "time": 0, "momentum": 0},
                      {"half": 1, "time": 360, "momentum": 0}],
            "episodes": [],
        },
        "reliability": {
            "life_boundaries": True, "damage_events": False,
            "capture_events": False, "ownership": False,
            "map_topology": True, "break_context": False,
            "positions": True, "flag_positions": True,
            "life_impact": True, "life_boundaries_inferred": True,
            "momentum": True,
        },
    }


def _tsv(columns, rows):
    return "\n".join([
        "\t".join(columns),
        *("\t".join(str(row.get(column, "NULL")) for column in columns)
          for row in rows),
    ]) + "\n"


class ExtractorDb:
    def sql(self, query):
        marker = query.split("lane_b_v5_", 1)[1].split(" ", 1)[0]
        if marker == "match":
            return _tsv(
                ["match_id", "server_id", "map_name", "halves_played",
                 "open_halves", "duration_seconds"],
                [{"match_id": "extractor-TEST", "server_id": 1,
                  "map_name": "dod_anzio", "halves_played": 1,
                  "open_halves": 0, "duration_seconds": 360}],
            )
        if marker == "roster":
            return _tsv(
                ["player_id", "player_name", "team"],
                [{"player_id": pid, "player_name": f"Bot {pid}",
                  "team": 1 if pid <= 6 else 2} for pid in range(1, 13)],
            )
        if marker == "positions":
            rows = []
            for when in range(0, 361, 5):
                for pid in range(1, 13):
                    team = 1 if pid <= 6 else 2
                    rows.append({"player_id": pid, "team": team, "half": 1,
                                 "pos_x": 500 + when * 5 if team == 1 else 3500 - when * 5,
                                 "pos_y": pid * 5, "pos_z": 0,
                                 "game_time": 500 + when})
            return _tsv(
                ["player_id", "team", "half", "pos_x", "pos_y", "pos_z", "game_time"],
                rows,
            )
        if marker == "frags":
            return _tsv(
                ["id", "half", "killer_id", "victim_id", "game_time"],
                [{"id": pid, "half": 1, "killer_id": pid,
                  "victim_id": pid + 6 if pid <= 6 else pid - 6,
                  "game_time": 100 + pid} for pid in range(1, 13)],
            )
        if marker == "damage":
            return _tsv(
                ["id", "half", "attacker_id", "victim_id", "damage_capped", "game_time"],
                [{"id": pid, "half": 1, "attacker_id": pid,
                  "victim_id": pid + 6 if pid <= 6 else pid - 6,
                  "damage_capped": 100, "game_time": 99 + pid}
                 for pid in range(1, 13)],
            )
        if marker == "assists":
            return _tsv(["player_id", "assists"], [{"player_id": 4, "assists": 1}])
        if marker == "teamkill_resets":
            assert "killerId AS killer_id" in query
            return _tsv(
                ["id", "half", "killer_id", "player_id", "game_time"],
                [{"id": 1, "half": 1, "killer_id": 1,
                  "player_id": 2, "game_time": 150}],
            )
        if marker == "suicide_resets":
            return _tsv(
                ["id", "half", "player_id", "game_time"],
                [{"id": 1, "half": 1, "player_id": 3, "game_time": 160}],
            )
        if marker == "captures":
            return _tsv(
                ["id", "half", "player_id", "capture_team", "flag_name", "game_time"],
                [{"id": 1, "half": 1, "player_id": 1, "capture_team": "Allies",
                  "flag_name": "POINT_ANZIO_STREET", "game_time": 180}],
            )
        if marker == "breaks":
            return ""
        if marker == "flags":
            names = ["POINT_ANZIO_LAUNDRY", "POINT_ANZIO_PLAZA",
                     "POINT_ANZIO_STREET", "POINT_BRIDGE", "POINT_ANZIO_HILL"]
            return _tsv(
                ["flag_index", "flag_name", "origin_x", "origin_y"],
                [{"flag_index": index, "flag_name": name,
                  "origin_x": index * 1000, "origin_y": 0}
                 for index, name in enumerate(names)],
            )
        if marker == "flag_states":
            names = ["POINT_ANZIO_LAUNDRY", "POINT_ANZIO_PLAZA",
                     "POINT_ANZIO_STREET", "POINT_BRIDGE", "POINT_ANZIO_HILL"]
            rows = [{"id": index + 1, "half": 1, "flag_index": index,
                     "flag_name": name, "owner_team": 1 if index < 2 else 2 if index > 2 else 0,
                     "is_initial": 1, "game_time": 500}
                    for index, name in enumerate(names)]
            rows.append({"id": 6, "half": 1, "flag_index": 2,
                         "flag_name": "POINT_ANZIO_STREET", "owner_team": 1,
                         "is_initial": 0, "game_time": 681})
            return _tsv(
                ["id", "half", "flag_index", "flag_name", "owner_team",
                 "is_initial", "game_time"], rows,
            )
        raise AssertionError(marker)


def test_live_database_extractor_builds_private_derived_public_facts():
    facts, private = build_facts(ExtractorDb(), "extractor-TEST")
    by_id = {row["player_id"]: row for row in facts["players"]}
    assert len(by_id) == 12
    assert by_id[1]["team_kills"] == 1
    assert by_id[2]["team_kills"] == 0
    assert by_id[3]["suicides"] == 1
    assert facts["reliability"]["ownership"] is True
    assert facts["reliability"]["momentum"] is True
    assert facts["momentum_summary"]["curve"]
    assert max(row["time"] for row in facts["momentum_summary"]["curve"]) <= 360
    body = json.dumps(facts).lower()
    assert "pos_x" not in body and "steam_id" not in body
    assert private["position_samples"] == 876


def test_damage_rows_are_bounded_to_the_victims_next_death():
    frags = [
        {"event_id": "frag-10", "half": 1, "time": 20,
         "killer_id": 7, "victim_id": 1},
        {"event_id": "frag-11", "half": 1, "time": 40,
         "killer_id": 8, "victim_id": 1},
    ]
    damage = [
        {"half": 1, "time": 10, "attacker_id": 7, "victim_id": 1,
         "damage_capped": 60},
        {"half": 1, "time": 30, "attacker_id": 8, "victim_id": 1,
         "damage_capped": 80},
    ]
    result = _associate_damage_to_deaths(
        damage, frags, {(1, 1): 1, (1, 7): 2, (1, 8): 2}
    )
    assert [row["death_event_id"] for row in result] == ["frag-10", "frag-11"]
    assert [row["victim_life_id"] for row in result] == [
        "h1-p1-frag-10", "h1-p1-frag-11",
    ]


def test_live_extractor_bundle_is_generated_verified_and_summarized(tmp_path: Path):
    result = generate_lane_b_report(ExtractorDb(), "extractor-TEST", tmp_path)
    assert result["verification"]["status"] == "PASS"
    assert len(result["report"]["players"]) == 12
    ratings = [row["impact_index"] for row in result["report"]["players"]]
    assert all(value is not None for value in ratings)
    assert min(ratings) <= 100 <= max(ratings)
    assert result["verification"]["private_derivation"]["retained"] is False
    assert json.loads((tmp_path / "report-verification.json").read_text())["status"] == "PASS"
    assert {"facts.normalized.json", "report.json", "report.md", "report.html",
            "manifest.json", "momentum.svg"} <= {
        path.name for path in tmp_path.iterdir()
    }
    assert "KTP accumulated match report" in (tmp_path / "report.html").read_text()
    summary = summary_for_lane(result)
    assert summary["status"] == "PASS"
    assert len(summary["players"]) == 12


def test_bundle_verifier_rejects_public_positional_data(monkeypatch, tmp_path: Path):
    facts = _facts()
    monkeypatch.setattr(
        "scripts.lane_b_match_report.build_facts",
        lambda *args, **kwargs: (facts, {"retained": False}),
    )
    from scripts import lane_b_match_report

    original = lane_b_match_report.build_bundle

    def leaking_bundle(input_facts, profile, output_dir):
        manifest = original(input_facts, profile, output_dir)
        path = output_dir / "report.json"
        report = json.loads(path.read_text())
        report["players"][0]["pos_x"] = 123
        path.write_text(json.dumps(report), encoding="utf-8")
        return manifest

    monkeypatch.setattr(lane_b_match_report, "build_bundle", leaking_bundle)
    with pytest.raises(ValueError, match="public report contains private keys"):
        generate_lane_b_report(object(), facts["match"]["match_id"], tmp_path)
