from __future__ import annotations

from pathlib import Path

from scripts import prepare_anzio_spatial_atlas as atlas


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests/e2e_stats/fixtures/regression-2026-08-14-anzio-5match"
FIXTURES = sorted(CORPUS.glob("match-*/hlstatsx-fixture.sql.gz"))


def test_committed_five_match_atlas_summary_is_stable():
    matches = [atlas.load_fixture(path) for path in FIXTURES]
    payload = atlas.build_atlas(matches, "1786721661-TEST")

    assert payload["summary"] == {
        "matches": 5,
        "target_coordinate_frags": 191,
        "target_raw_frags": 194,
        "corpus_coordinate_frags": 714,
        "corpus_raw_frags": 739,
        "position_samples": 10982,
        "capture_events": 83,
        "cap_breaks": 17,
        "reconstructed_capouts": 0,
        "trade_kills": 0,
        "fast_multikill_frags": 199,
        "isolated_deaths": 0,
        "damage_aligned": 1890,
        "damage_total": 1890,
    }
    names = [panel["name"] for panel in payload["panels"]]
    assert len(names) == len(set(names))
    assert {
        "01-target-aggregate-occupancy.png",
        "05-target-kills-per-occupancy-minute.png",
        "26-corpus-recurring-kill-lanes.png",
        "37-target-objective-efficiency.png",
        "42-target-vs-baseline-kill-rate.png",
        "46-atlas-coverage-and-limitations.png",
    } <= set(names)


def test_atlas_render_payload_is_aggregate_only():
    matches = [atlas.load_fixture(path) for path in FIXTURES]
    payload = atlas.build_atlas(matches, "1786721661-TEST")
    serialized = str(payload).lower()
    for forbidden in (
        "steam_id", "player_name", "player_id", "killer_id", "victim_id",
        "attacker_id", "assister_id",
    ):
        assert forbidden not in serialized
    assert payload["privacy"].startswith("Aggregate-only")


def test_weapon_groups_are_exhaustive_for_observed_weapons():
    matches = [atlas.load_fixture(path) for path in FIXTURES]
    observed = {frag["weapon_group"] for match in matches for frag in match["frags"]}
    assert observed <= {
        "rifle", "automatic", "machine-gun", "sniper", "explosive",
        "sidearm-melee", "other",
    }
    assert "other" not in observed
