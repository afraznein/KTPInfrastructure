"""Per-hit damage is decided per match, not per archive.

The live database carries ktp_damage_events for every match it holds, but the
ledger was born partway through the archive. A match that ended before its
first hit gets Statsme damage dealt and an unknown (null) for everything only
the per-hit ledger can supply, never a 0. A covered match is unchanged.
"""
from __future__ import annotations

from pathlib import Path

from scripts import match_analytics as analytics
from scripts.analytics_report_dto import sanitize_report
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/e2e_stats/fixtures/analytics-phase-a-contract.sql"
COVERED = "phase-a-contract-TEST"
LEGACY = "legacy-before-damage-ledger-TEST"
QUIET = "covered-no-damage-TEST"
PER_HIT_ONLY = ("damage_taken", "damage_differential", "grenade_damage",
                "grenade_damage_taken")
TEAM_PER_HIT_ONLY = PER_HIT_ONLY + ("team_damage",)
# The cache books damage twice (the March double-count shape); Statsme's own
# frags match the cache's kills, so Statsme is the corroborated source.
STATSME_DAMAGE = {1: 140, 7: 95}


def _add_match(db: EphemeralMysql, match_id: str, day: str,
               legacy_damage: bool) -> None:
    db.sql(f"""
INSERT INTO ktp_matches VALUES
  ('{match_id}',2,'dod_anzio',1,0,'{day} 20:00:00','{day} 20:10:00'),
  ('{match_id}',2,'dod_anzio',2,0,'{day} 20:11:00','{day} 20:21:00');
INSERT INTO ktp_match_players VALUES
  ('{match_id}',1,'BOT:0001','Allies 1',1,'{day} 20:00:00'),
  ('{match_id}',7,'BOT:0007','Axis 1',2,'{day} 20:00:00');
INSERT INTO hlstats_Events_Frags
  (match_id, killerId, victimId, weapon, headshot, half) VALUES
  ('{match_id}',1,7,'garand',1,1),
  ('{match_id}',7,1,'k98',0,2);
""")
    if legacy_damage:
        db.sql(f"""
INSERT INTO ktp_match_stats (match_id, player_id, half, kills, deaths, score, damage)
VALUES ('{match_id}',1,0,1,1,0,{2 * STATSME_DAMAGE[1]}),
       ('{match_id}',7,0,1,1,0,{2 * STATSME_DAMAGE[7]});
INSERT INTO hlstats_Events_Statsme
  (match_id, half, playerId, weapon, shots, hits, headshots, damage, kills, deaths)
VALUES ('{match_id}',1,1,'garand',10,4,1,{STATSME_DAMAGE[1]},1,0),
       ('{match_id}',2,7,'k98',8,3,0,{STATSME_DAMAGE[7]},1,0);
""")


def _check(report: dict, code: str) -> dict | None:
    return next((c for c in report["quality"]["checks"] if c["code"] == code), None)


def test_damage_is_gated_on_the_ledger_covering_the_match(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        analytics.load_fixture(db, FIXTURE)
        # Production's ktp_match_stats carries damage; the fixture's does not.
        db.sql("ALTER TABLE ktp_match_stats ADD COLUMN damage int")
        # The fixture's damage ledger first fires on 2026-08-16.
        _add_match(db, LEGACY, "2026-01-20", legacy_damage=True)
        _add_match(db, QUIET, "2026-09-01", legacy_damage=False)
        sources = analytics.source_capabilities(db)
        covered_fact = analytics.query_rows(db, "player_match_fact.sql", COVERED)
        covered = analytics.build_report(db, COVERED, FIXTURE, sources)
        legacy = analytics.build_report(db, LEGACY, FIXTURE, sources)
        quiet = analytics.build_report(db, QUIET, FIXTURE, sources)

    # The archive has the table, so an archive-wide decision says per-hit.
    assert sources["per_hit_damage"] is True

    assert legacy["source_coverage"]["per_hit_damage"] is False
    assert _check(legacy, "damage_source_not_captured")["level"] == "WARN"
    assert _check(legacy, "legacy_damage_source")["evidence"]["source"] == "statsme"
    by_id = {p["player_id"]: p for p in legacy["players"]}
    for pid, damage in STATSME_DAMAGE.items():
        assert by_id[pid]["damage_dealt"] == damage
        assert by_id[pid]["damage_per_life"] == float(damage)
        for field in PER_HIT_ONLY + ("team_damage", "self_damage"):
            assert by_id[pid][field] is None, (field, by_id[pid])
    assert all(w["damage_dealt"] is None for w in legacy["weapons"])
    for team in legacy["teams"]:
        assert team["damage_dealt"] == sum(
            STATSME_DAMAGE[p["player_id"]] for p in legacy["players"]
            if p["team"] == team["team"])
        for field in TEAM_PER_HIT_ONLY + ("self_damage",):
            assert team[field] is None, (field, team)

    legacy_dto = sanitize_report(legacy)
    for player in legacy_dto["players"]:
        assert player["damage_dealt"] in STATSME_DAMAGE.values()
        for field in PER_HIT_ONLY:
            assert player[field] is None, (field, player)
    for team in legacy_dto["teams"]:
        assert team["damage_dealt"] is not None
        for field in TEAM_PER_HIT_ONLY:
            assert team[field] is None, (field, team)
    assert legacy_dto["player_halves"]["rows"]
    for row in legacy_dto["player_halves"]["rows"]:
        for field in ("damage_dealt", "team_damage") + PER_HIT_ONLY:
            assert row[field] is None, (field, row)
    assert all(w["damage_dealt"] is None for w in legacy_dto["weapons"])

    # Covered: per-hit, straight from the ledger, no legacy fallback.
    assert covered["source_coverage"]["per_hit_damage"] is True
    assert _check(covered, "damage_source_not_captured") is None
    assert _check(covered, "damage_balance")["level"] == "PASS"
    fact = {r["player_id"]: r for r in covered_fact}
    for player in covered["players"]:
        for field in ("damage_dealt", "damage_taken", "team_damage",
                      "self_damage", "grenade_damage", "grenade_damage_taken"):
            assert player[field] == fact[player["player_id"]][field], field
    assert sum(p["damage_dealt"] for p in covered["players"]) > 0
    assert all(t["damage_taken"] is not None for t in covered["teams"])

    # Covered with no hits: a measured zero stays zero.
    assert quiet["source_coverage"]["per_hit_damage"] is True
    for player in quiet["players"]:
        for field in ("damage_dealt", "damage_taken", "team_damage", "self_damage"):
            assert player[field] == 0, (field, player)
