from __future__ import annotations

import json
from pathlib import Path

from scripts import spatial_map_registry as registry


ROOT = Path(__file__).resolve().parents[2]


def real_registry():
    config = registry.read_json(ROOT / "config/analytics/spatial_maps/registry.json")
    return registry.build_registry(config, ROOT / "config/local/dod-configs", ROOT)


def test_every_ktp_match_config_is_in_the_valid_registry():
    result = real_registry()
    expected_configs = list((ROOT / "config/local/dod-configs").glob("ktp_*.cfg"))
    represented_configs = sum(len(item["match_configs"]) for item in result["maps"])
    assert result["valid"], result["errors"]
    assert represented_configs == len(expected_configs)


def test_only_anzio_is_synthetic_ready_and_none_are_competitive_ready():
    result = real_registry()
    by_map = {item["map_name"]: item for item in result["maps"]}
    assert by_map["dod_anzio"]["status"] == "synthetic_ready"
    assert result["counts"] == {
        "competitive_ready": 0,
        "synthetic_ready": 1,
        "blocked": len(result["maps"]) - 1,
    }
    assert all(
        not item["bot_waypoints_verified"]
        for item in result["maps"] if item["map_name"] != "dod_anzio"
    )


def test_next_priority_maps_are_explicit_but_blocked():
    by_map = {item["map_name"]: item for item in real_registry()["maps"]}
    assert [by_map[name]["priority"] for name in (
        "dod_anzio", "dod_harrington", "dod_lennon_test", "dod_saints"
    )] == [1, 2, 3, 4]
    assert all(by_map[name]["status"] == "blocked" for name in (
        "dod_harrington", "dod_lennon_test", "dod_saints"
    ))


def test_ready_map_with_missing_spatial_config_fails_validation(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "ktp_example.cfg").write_text(
        "say KTP dod_example Match Config Executed\n", encoding="utf-8"
    )
    config = {
        "minimum_synthetic_matches": 5,
        "minimum_human_matches": 20,
        "defaults": {field: True for field in registry.REVIEW_FIELDS},
        "maps": {"dod_example": {"synthetic_matches": 5}},
    }
    result = registry.build_registry(config, config_dir, tmp_path)
    assert not result["valid"]
    assert "has no spatial_config" in result["errors"][0]


def test_cli_writes_machine_and_human_reports(tmp_path):
    exit_code = registry.main(["--output-dir", str(tmp_path)])
    assert exit_code == 0
    payload = json.loads((tmp_path / "spatial-map-registry.json").read_text())
    markdown = (tmp_path / "SPATIAL_MAP_READINESS.md").read_text()
    assert payload["counts"]["synthetic_ready"] == 1
    assert "dod_anzio | synthetic_ready" in markdown
    assert "dod_harrington | blocked" in markdown
