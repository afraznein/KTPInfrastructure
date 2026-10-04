"""A box-score count whose producer did not exist yet is absent, never zero.

Assists, cap breaks and capture credits each come from a producer that was
born partway through the archive. A match that ended before a producer's
first event cannot have measured it, so a 0 there would be a claim about real
players that no source supports. A match the producer covered, with genuinely
no events, still reads 0.
"""
from __future__ import annotations

from pathlib import Path

from scripts import match_analytics as analytics
from scripts.analytics_report_dto import sanitize_report
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/e2e_stats/fixtures/analytics-phase-a-contract.sql"
COVERED = "phase-a-contract-TEST"
LEGACY = "legacy-before-producers-TEST"
QUIET = "covered-no-events-TEST"
PRODUCER_DATED = ("assists", "capture_credits", "cap_breaks")


def _add_match(db: EphemeralMysql, match_id: str, day: str) -> None:
    """Two closed halves, a 1v1 roster and two frags -- nothing else."""
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


def _facts(db: EphemeralMysql, match_id: str):
    return (analytics.query_rows(db, "player_match_fact.sql", match_id),
            analytics.query_rows(db, "player_half_fact.sql", match_id))


def test_producer_dated_counts_are_null_before_the_producer_and_zero_after(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        analytics.load_fixture(db, FIXTURE)
        # LEGACY also predates the damage ledger, so its report reads legacy
        # damage: production's ktp_match_stats carries it, the fixture's does not.
        db.sql("ALTER TABLE ktp_match_stats ADD COLUMN damage int")
        # The fixture's producers first fire on 2026-08-16.
        _add_match(db, LEGACY, "2026-01-20")
        _add_match(db, QUIET, "2026-09-01")
        covered_match, covered_halves = _facts(db, COVERED)
        legacy_match, legacy_halves = _facts(db, LEGACY)
        quiet_match, quiet_halves = _facts(db, QUIET)
        legacy_report = analytics.build_report(db, LEGACY, FIXTURE)
        quiet_report = analytics.build_report(db, QUIET, FIXTURE)

    assert sum(r["assists"] for r in covered_match) == 3
    assert sum(r["cap_breaks"] for r in covered_match) == 2
    assert sum(r["capture_credits"] for r in covered_match) == 3
    assert sum(r["assists"] for r in covered_halves) == 3
    assert sum(r["cap_breaks"] for r in covered_halves) == 2
    assert sum(r["capture_credits"] for r in covered_halves) == 3

    assert len(legacy_match) == 2 and len(legacy_halves) == 4
    for row in legacy_match + legacy_halves:
        for field in PRODUCER_DATED:
            assert row[field] is None, (field, row)
    assert all(row["kda_ratio"] is None for row in legacy_match)
    # Frags existed all along, so they stay filled.
    assert sum(r["kills"] for r in legacy_match) == 2
    assert sum(r["headshots"] for r in legacy_match) == 1

    assert len(quiet_match) == 2 and len(quiet_halves) == 4
    for row in quiet_match + quiet_halves:
        for field in PRODUCER_DATED:
            assert row[field] == 0, (field, row)
    assert all(row["kda_ratio"] == 1.0 for row in quiet_match)

    legacy_dto = sanitize_report(legacy_report)
    for player in legacy_dto["players"]:
        for field in PRODUCER_DATED:
            assert player[field] is None, (field, player)
    for team in legacy_dto["teams"]:
        for field in PRODUCER_DATED:
            assert team[field] is None, (field, team)
    assert legacy_dto["player_halves"]["rows"]
    for row in legacy_dto["player_halves"]["rows"]:
        for field in PRODUCER_DATED:
            assert row[field] is None, (field, row)
    assert legacy_dto["player_halves"]["reconciled"] is True

    quiet_dto = sanitize_report(quiet_report)
    for block in (quiet_dto["players"], quiet_dto["teams"],
                  quiet_dto["player_halves"]["rows"]):
        assert block
        for row in block:
            for field in PRODUCER_DATED:
                assert row[field] == 0, (field, row)
