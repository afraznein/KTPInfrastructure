from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import spatial_map_registry as registry


ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config/local/dod-configs"
MAPS_INI = ROOT / "config/local/ktp_maps.ini"

# Real maps the fleet plays whose match config announces a DIFFERENT name, so
# the old say-line discovery could not see any of them. These are the control:
# they must be discovered, and the assertion fails against say-line discovery.
POOL_MAPS_THE_SAY_LINE_HID = (
    "dod_lennon5_b1",
    "dod_armory_b7",
    "dod_saints2_b5e",
    "dod_railroad2_s10a",
    "dod_solitude2",
)

# The other half of the control. These are the names the say lines announce --
# strings that are not maps and that nothing can ever load. Discovery must not
# invent them, and neither must it invent an outright bogus map.
NAMES_THAT_ARE_NOT_MAPS = (
    "dod_lennon_test",
    "dod_saints",
    "dod_armory_test",
    "dod_solitude_test",
    "dod_not_a_map_at_all",
)


def real_registry():
    config = registry.read_json(ROOT / "config/analytics/spatial_maps/registry.json")
    return registry.build_registry(config, CONFIG_DIR, MAPS_INI, ROOT)


def discovered_names(result):
    return {item["map_name"] for item in result["maps"]}


def test_maps_the_say_line_hid_are_discovered():
    names = discovered_names(real_registry())
    missing = [name for name in POOL_MAPS_THE_SAY_LINE_HID if name not in names]
    assert not missing, f"pool maps still invisible to discovery: {missing}"


def test_names_that_no_map_carries_are_not_discovered():
    names = discovered_names(real_registry())
    invented = [name for name in NAMES_THAT_ARE_NOT_MAPS if name in names]
    assert not invented, f"discovery invented map names: {invented}"


def test_discovery_matches_the_bindings_the_server_reads():
    result = real_registry()
    assert discovered_names(result) == set(registry.parse_maps_ini(MAPS_INI))
    assert result["valid"], result["errors"]


def test_a_config_no_map_is_bound_to_is_reported_not_dropped():
    result = real_registry()
    referenced = {
        Path(path).name
        for item in result["maps"]
        for path in item["match_configs"]
    }
    reported = {Path(path).name for path in result["unreferenced_configs"]}
    on_disk = {path.name for path in CONFIG_DIR.glob("ktp_*.cfg")}
    assert referenced | reported == on_disk
    assert not referenced & reported


def test_a_binding_with_no_config_keeps_the_map_and_reports_the_gap(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "ktp_real.cfg").write_text("// present\n", encoding="utf-8")
    maps_ini = tmp_path / "ktp_maps.ini"
    maps_ini.write_text(
        "[dod_real]\nconfig = ktp_real.cfg\n\n[dod_dangling]\nconfig = ktp_gone.cfg\n",
        encoding="utf-8",
    )
    found = registry.discover_configs(config_dir, maps_ini, tmp_path)
    assert set(found.maps) == {"dod_real", "dod_dangling"}
    assert found.maps["dod_dangling"] == []
    assert found.unresolved_bindings == ["dod_dangling -> configs/ktp_gone.cfg"]
    assert not found.errors


def test_a_stale_say_line_is_reported_without_steering_discovery(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "ktp_saints.cfg").write_text(
        "say KTP dod_saints Match Config Executed\n", encoding="utf-8"
    )
    maps_ini = tmp_path / "ktp_maps.ini"
    maps_ini.write_text("[dod_saints2_b3e]\nconfig = ktp_saints.cfg\n", encoding="utf-8")
    found = registry.discover_configs(config_dir, maps_ini, tmp_path)
    assert set(found.maps) == {"dod_saints2_b3e"}
    assert found.announcement_mismatches == [
        "configs/ktp_saints.cfg: announces dod_saints, bound to dod_saints2_b3e"
    ]


def test_one_config_serving_several_map_revisions_is_not_a_mismatch(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "ktp_anzio.cfg").write_text(
        "say KTP dod_anzio Match Config Executed\n", encoding="utf-8"
    )
    maps_ini = tmp_path / "ktp_maps.ini"
    maps_ini.write_text(
        "[dod_anzio]\nconfig = ktp_anzio.cfg\n\n[dod_anzio_test4d]\nconfig = ktp_anzio.cfg\n",
        encoding="utf-8",
    )
    found = registry.discover_configs(config_dir, maps_ini, tmp_path)
    assert set(found.maps) == {"dod_anzio", "dod_anzio_test4d"}
    assert found.announcement_mismatches == []


def test_a_missing_bindings_file_is_an_error_not_an_empty_inventory(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "ktp_real.cfg").write_text("// present\n", encoding="utf-8")
    found = registry.discover_configs(config_dir, tmp_path / "absent.ini", tmp_path)
    assert found.maps == {}
    assert found.errors == ["absent.ini: map bindings file not found"]


def test_ini_parse_mirrors_the_plugin(tmp_path):
    maps_ini = tmp_path / "ktp_maps.ini"
    maps_ini.write_text(
        "; comment\n"
        "# comment\n"
        "[DOD_Mixed.bsp]\n"
        "name = Mixed\n"
        "config = ktp_mixed.cfg\n"
        "config = ktp_ignored.cfg\n"
        "\n"
        # A section stays open across blank lines until a config key closes it,
        # so this distant key binds to dod_separated. The plugin does the same.
        "[dod_separated]\n"
        "name = Config key is further down\n"
        "\n"
        "config = ktp_separated.cfg\n",
        encoding="utf-8",
    )
    assert registry.parse_maps_ini(maps_ini) == {
        "dod_mixed": "ktp_mixed.cfg",
        "dod_separated": "ktp_separated.cfg",
    }


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


def test_the_review_queue_leads_with_maps_the_fleet_actually_plays():
    by_map = {item["map_name"]: item for item in real_registry()["maps"]}
    queue = ("dod_anzio", "dod_lennon5_b1", "dod_armory_b7",
             "dod_harrington", "dod_saints2_b5e", "dod_thunder2")
    assert [by_map[name]["priority"] for name in queue] == [1, 2, 3, 4, 5, 6]
    assert all(by_map[name]["status"] == "blocked" for name in queue[1:])


def test_ready_map_with_missing_spatial_config_fails_validation(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "ktp_example.cfg").write_text("// present\n", encoding="utf-8")
    maps_ini = tmp_path / "ktp_maps.ini"
    maps_ini.write_text("[dod_example]\nconfig = ktp_example.cfg\n", encoding="utf-8")
    config = {
        "minimum_synthetic_matches": 5,
        "minimum_human_matches": 20,
        "defaults": {field: True for field in registry.REVIEW_FIELDS},
        "maps": {"dod_example": {"synthetic_matches": 5}},
    }
    result = registry.build_registry(config, config_dir, maps_ini, tmp_path)
    assert not result["valid"]
    assert "has no spatial_config" in result["errors"][0]


def test_cli_writes_machine_and_human_reports(tmp_path):
    exit_code = registry.main(["--output-dir", str(tmp_path)])
    assert exit_code == 0
    payload = json.loads((tmp_path / "spatial-map-registry.json").read_text())
    markdown = (tmp_path / "SPATIAL_MAP_READINESS.md").read_text()
    assert payload["counts"]["synthetic_ready"] == 1
    assert "dod_anzio | synthetic_ready" in markdown
    assert "dod_lennon5_b1 | blocked" in markdown
    # The section rendered only while the dev profile bound configs it does not ship.
    assert payload["unresolved_bindings"] == []
    assert "## Bindings whose match config is missing" not in markdown
    assert "## Match configs no map is bound to" in markdown


# --- human_matches is derived from ktp_capture_manifests, never hand-entered ----

class FakeCli:
    def __init__(self, rows: str = ""):
        self.rows, self.sent = rows, []

    def execute(self, sql: str) -> str:
        self.sent.append(sql)
        return self.rows


# The 2026-10-09 production read, counted with --since 2026-09-15.
MEASURED = "dod_anzio\t73\ndod_harrington\t70\ndod_lennon5_b1\t60\ndod_saints2_b5e\t40\n"


def test_a_hand_entered_human_matches_is_a_validation_error(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "ktp_example.cfg").write_text("// present\n", encoding="utf-8")
    maps_ini = tmp_path / "ktp_maps.ini"
    maps_ini.write_text("[dod_example]\nconfig = ktp_example.cfg\n", encoding="utf-8")
    config = {"defaults": {"human_matches": 0}, "maps": {"dod_example": {"human_matches": 25}}}
    result = registry.build_registry(config, config_dir, maps_ini, tmp_path)
    assert not result["valid"]
    assert [e for e in result["errors"] if "never hand-entered" in e] == [
        "defaults: human_matches is derived from ktp_capture_manifests, never hand-entered",
        "dod_example: human_matches is derived from ktp_capture_manifests, never hand-entered",
    ]
    # And the typed 25 is not what the entry reports.
    assert result["maps"][0]["human_matches"] is None


def test_the_shipped_registry_types_no_human_matches():
    config = registry.read_json(ROOT / "config/analytics/spatial_maps/registry.json")
    assert registry.hand_entered_human_matches(config) == []


def test_without_a_count_human_matches_is_unknown_not_zero():
    result = real_registry()
    assert result["human_matches_source"] is None
    assert all(item["human_matches"] is None for item in result["maps"])


def test_counted_human_matches_land_on_every_map_and_open_the_competitive_gate():
    config = registry.read_json(ROOT / "config/analytics/spatial_maps/registry.json")
    counts = registry.human_match_counts(FakeCli(MEASURED))
    result = registry.build_registry(config, CONFIG_DIR, MAPS_INI, ROOT, human_matches=counts)
    by_map = {item["map_name"]: item for item in result["maps"]}
    assert result["valid"], result["errors"]
    assert result["human_matches_source"] == "ktp_capture_manifests"
    assert by_map["dod_anzio"]["human_matches"] == 73
    assert by_map["dod_lennon5_b1"]["human_matches"] == 60
    # A bound map with no manifest is a counted zero, not unknown.
    assert by_map["dod_donner"]["human_matches"] == 0
    # Anzio is the one fully reviewed map, so 73 >= 20 makes it competitive_ready.
    assert by_map["dod_anzio"]["status"] == "competitive_ready"
    assert by_map["dod_lennon5_b1"]["status"] == "blocked"


def test_the_count_query_is_distinct_match_ids_per_map_with_an_optional_since():
    cli = FakeCli()
    registry.human_match_counts(cli)
    registry.human_match_counts(cli, since="2026-09-15")
    assert all("COUNT(DISTINCT match_id) FROM ktp_capture_manifests" in q for q in cli.sent)
    assert "WHERE" not in cli.sent[0]
    assert "WHERE event_time >= '2026-09-15'" in cli.sent[1]


def test_since_must_be_a_date():
    with pytest.raises(ValueError):
        registry.human_match_counts(FakeCli(), since="2026-09-15' OR 1=1 -- ")


def test_cli_counts_from_the_database_when_asked(tmp_path, monkeypatch):
    seen = {}

    class Cli(FakeCli):
        def __init__(self, *, database, defaults_extra_file=None):
            super().__init__(MEASURED)
            seen["database"] = database

    monkeypatch.setattr(registry, "MysqlCli", Cli)
    assert registry.main(["--output-dir", str(tmp_path), "--database", "hlstatsx"]) == 0
    payload = json.loads((tmp_path / "spatial-map-registry.json").read_text())
    markdown = (tmp_path / "SPATIAL_MAP_READINESS.md").read_text(encoding="utf-8")
    assert seen["database"] == "hlstatsx"
    assert {m["map_name"]: m["human_matches"] for m in payload["maps"]}["dod_harrington"] == 70
    assert "counted from `ktp_capture_manifests`, never hand-entered" in markdown
