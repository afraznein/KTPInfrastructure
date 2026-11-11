"""The identity nothing compared: ingest damage against the report's partition.

`ktp_match_stats.damage` is every hit the attacker landed -- the ingest query
groups `ktp_damage_events` by `attacker_id` with no victim join and no team
predicate. The report splits the same `damage_capped` into `damage_dealt`
(opponent only), `team_damage` and `self_damage`. So `damage_dealt` alone is
never the comparable quantity, and before this the only damage checks were
`damage_balance` (dealt == taken, internally consistent and blind to the ingest
side) and `legacy_damage_source` (legacy matches only).

The second check here holds the partition's own precondition: the three CASE
arms in `player_match_fact.sql` read the teams through `LEFT JOIN roster`, so a
hit whose victim is off the roster puts both team comparisons at NULL, neither
arm fires, and the damage reaches no column while the ingest side counts it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.match_analytics import INTEGER_COLUMNS, _value, evaluate_quality

MATCH = "1788919258-CHI1"
REPO = Path(__file__).resolve().parents[2]

# Only the per-hit branch of evaluate_quality is under test here; these are the
# flags that reach it.
SOURCES = {
    "per_hit_damage": True, "capture_credits": True, "positions": True,
    "flag_ownership": True, "statsme": True, "statsme2": True,
    "legacy_match_cache": True, "assists": True,
}

NEW_COLUMNS = (
    "cached_damage", "cached_damage_rows", "cached_damage_off_roster",
    "unpartitioned_damage_dealt", "unpartitioned_hits_dealt",
    "unpartitioned_damage_taken", "unpartitioned_hits_taken",
    "cross_tagged_damage_rows",
)


def _players(dealt: int, taken: int, team: int, own: int) -> list[dict]:
    """Two roster rows. Both carry `dealt` once, so the summed opponent damage
    is twice it -- which is what makes the identity arithmetic below explicit
    rather than an echo of one row."""
    return [
        {"steam_id": "STEAM_0:0:1", "kills": 1, "deaths": 1,
         "damage_dealt": dealt, "damage_taken": taken,
         "team_damage": team, "self_damage": own},
        {"steam_id": "STEAM_0:0:2", "kills": 1, "deaths": 1,
         "damage_dealt": taken, "damage_taken": dealt,
         "team_damage": 0, "self_damage": 0},
    ]


def _inventory(**over) -> dict:
    base = {
        "roster_players": 2, "distinct_roster_players": 2,
        "invalid_half_frags": 0, "invalid_half_damage": 0,
        "damage_events": 40,
        "cached_player_totals": 2, "cached_kills": 2, "cached_deaths": 2,
        "cached_damage": 0, "cached_damage_rows": 2,
        "cached_damage_off_roster": 0,
        "unpartitioned_damage_dealt": 0, "unpartitioned_hits_dealt": 0,
        "unpartitioned_damage_taken": 0, "unpartitioned_hits_taken": 0,
        "cross_tagged_damage_rows": 0,
        "statsme_rows": 1, "statsme2_rows": 0,
        "capture_credits": 0, "unique_capture_events": 0,
        "position_samples": 1,
    }
    base.update(over)
    return base


def _check(code: str, players: list[dict], inventory: dict):
    checks = evaluate_quality(
        MATCH, {"open_halves": 0}, players, inventory, SOURCES)["checks"]
    found = [c for c in checks if c["code"] == code]
    assert len(found) <= 1, f"{code} emitted {len(found)} times"
    return found[0] if found else None


# --- the identity -----------------------------------------------------------

def test_the_whole_partition_reconciles_with_the_ingest_total():
    """6000 + 6000 opponent, 400 friendly, 220 self: 12620 is what the ingest
    query sums, because it has no victim join and no team predicate."""
    got = _check("damage_reconciliation",
                 _players(dealt=6000, taken=6000, team=400, own=220),
                 _inventory(cached_damage=12620))
    assert got["level"] == "PASS", got
    assert got["evidence"]["fact_damage"] == 12620


def test_damage_dealt_alone_does_not_satisfy_the_check():
    """The defect this exists for: a cache equal to opponent damage only.

    That is the comparison that produced one match's 6621 against 6460 and read
    as a mismatch. It has to FAIL here, because agreeing would mean the check
    had adopted the wrong quantity.
    """
    got = _check("damage_reconciliation",
                 _players(dealt=6000, taken=6000, team=400, own=220),
                 _inventory(cached_damage=12000))
    assert got["level"] == "FAIL", got
    assert got["evidence"]["team_damage"] == 400
    assert got["evidence"]["self_damage"] == 220


def test_a_short_ingest_total_fails():
    """Negative control: one unit of disagreement is still a FAIL, so the PASS
    above is a verdict rather than a check that stopped discriminating."""
    assert _check("damage_reconciliation",
                  _players(dealt=6000, taken=6000, team=0, own=0),
                  _inventory(cached_damage=11999))["level"] == "FAIL"


def test_no_cached_damage_figure_warns_rather_than_passing_on_zero():
    """The daemon writes NULL damage for a half it has no ledger rows for, so
    an absent figure is not a cached zero. Comparing against a COALESCE'd 0
    would PASS every match whose report damage is also 0."""
    got = _check("damage_reconciliation", _players(0, 0, 0, 0),
                 _inventory(cached_damage=0, cached_damage_rows=0))
    assert got["level"] == "WARN", got
    assert "cached_damage" not in got["evidence"]


def test_the_check_is_absent_on_a_legacy_match():
    """A legacy match's ktp_match_stats.damage comes from other producers
    entirely; `legacy_damage_source` is what speaks there."""
    checks = evaluate_quality(
        MATCH, {"open_halves": 0}, _players(1, 1, 0, 0), _inventory(),
        dict(SOURCES, per_hit_damage=False))["checks"]
    codes = [c["code"] for c in checks]
    assert "damage_reconciliation" not in codes
    assert "legacy_damage_source" in codes  # control: the branch did run


def test_the_check_is_absent_when_no_per_hit_rows_exist():
    checks = evaluate_quality(
        MATCH, {"open_halves": 0}, _players(0, 0, 0, 0),
        _inventory(damage_events=0), SOURCES)["checks"]
    codes = [c["code"] for c in checks]
    assert "damage_reconciliation" not in codes
    assert "damage_missing" in codes  # control


# --- the partition's own precondition ---------------------------------------

def test_an_exhaustive_partition_passes():
    got = _check("damage_partition_exhaustive", _players(10, 10, 0, 0),
                 _inventory(cached_damage=20))
    assert got["level"] == "PASS", got


@pytest.mark.parametrize("damage,hits", [
    ("unpartitioned_damage_dealt", "unpartitioned_hits_dealt"),
    ("unpartitioned_damage_taken", "unpartitioned_hits_taken"),
])
def test_either_side_of_the_hole_fails_the_partition(damage, hits):
    """Both `LEFT JOIN roster` sides carry it -- the dealt arms through the
    victim, `damage_taken` through the attacker -- so a check watching one side
    would report an exhaustive partition on the other's hole."""
    got = _check("damage_partition_exhaustive", _players(10, 10, 0, 0),
                 _inventory(cached_damage=20, **{damage: 143, hits: 2}))
    assert got["level"] == "FAIL", got
    assert got["evidence"][damage] == 143
    assert got["evidence"][hits] == 2


def test_an_unpartitioned_hole_is_exactly_what_breaks_the_identity():
    """The two checks are one defect seen twice: the ingest side counts the hit
    and the report does not, so the deficit equals the unpartitioned total. A
    FAIL on the identity has to name that cause, or the next reader measures
    the population again to find it."""
    players = _players(dealt=6000, taken=6000, team=0, own=0)
    inventory = _inventory(cached_damage=12143, unpartitioned_damage_dealt=143,
                           unpartitioned_hits_dealt=2)
    recon = _check("damage_reconciliation", players, inventory)
    partition = _check("damage_partition_exhaustive", players, inventory)
    assert recon["level"] == "FAIL" and partition["level"] == "FAIL"
    deficit = (recon["evidence"]["cached_damage"]
               - recon["evidence"]["fact_damage"])
    assert deficit == partition["evidence"]["unpartitioned_damage_dealt"]


# --- the inventory query has to supply what the checks read -----------------

def test_the_inventory_query_selects_every_column_the_checks_read():
    """A check reading an inventory key the query does not select takes the
    `.get(..., 0)` default -- a PASS with nothing behind it. This is what pins
    the two files together."""
    sql = (REPO / "sql" / "analytics" / "quality_inventory.sql").read_text(
        encoding="utf-8")
    # The alias has to END here: a substring test passes on
    # `AS unpartitioned_hits_taken_x`, which selects a column no check reads.
    selected = set(re.findall(r"\bAS\s+([A-Za-z0-9_]+)", sql))
    for column in NEW_COLUMNS:
        assert column in selected, column
    # Control: a name the query must not carry, so the assertions above are
    # reading the file rather than matching anything put in front of them.
    assert "cached_damage_per_minute" not in selected


def test_the_new_inventory_columns_are_coerced_to_integers():
    """`_value` returns a string for any column not listed, and `"143" != 143`,
    so an unlisted column would fail every identity it reached."""
    for column in NEW_COLUMNS:
        assert column in INTEGER_COLUMNS, column
        assert _value(column, "143") == 143
    # Control: the coercion is per column, not applied to everything.
    assert _value("map_name", "143") == "143"


def test_a_ledger_row_tagged_for_another_match_warns_rather_than_failing():
    """A row whose producer context names a different match is in the ingest
    total (which sums by `match_id`) and out of the box score (which defers to
    the producer). The totals then cannot settle either way: FAILing would
    name the wrong cause, and silence would hide it."""
    got = _check("damage_reconciliation",
                 _players(dealt=6000, taken=6000, team=0, own=0),
                 _inventory(cached_damage=12000, cross_tagged_damage_rows=1))
    assert got["level"] == "WARN", got
    assert got["evidence"]["cross_tagged_damage_rows"] == 1
    # The comparison did not happen, so the cached figure is not evidence.
    assert "cached_damage" not in got["evidence"]


def test_the_cross_tag_gate_does_not_swallow_a_real_disagreement():
    """Control for the test above: with no cross-tagged row the same numbers
    FAIL, so the WARN is the gate firing and not the check giving up."""
    got = _check("damage_reconciliation",
                 _players(dealt=6000, taken=6000, team=0, own=0),
                 _inventory(cached_damage=12001))
    assert got["level"] == "FAIL", got


# --- the e2e fixture has to carry the column the query reads ----------------

FIXTURE = (REPO / "tests" / "e2e_stats" / "fixtures"
           / "analytics-phase-a-contract.sql")


def _match_stats_ddl() -> list[str]:
    # The closing paren is the one starting a line; the first `)` in the text
    # is inside `varchar(64)`.
    block = FIXTURE.read_text(encoding="utf-8").split(
        "CREATE TABLE ktp_match_stats (", 1)[1].split("\n)", 1)[0]
    flat = re.sub(r"\([^)]*\)", "", block).replace("\n", " ")
    return [c.split()[0] for c in flat.split(",") if c.split()]


def test_the_contract_fixture_carries_the_cached_damage_column():
    """`quality_inventory.sql` selects `ktp_match_stats.damage` for every match,
    so a fixture without the column is not a wrong number -- the query dies on
    `Unknown column` and only the corpus lane finds out, twenty minutes in.
    Production has carried it since `migrate_002_half_damage_score.sql`."""
    columns = _match_stats_ddl()
    assert "damage" in columns, columns
    assert "score" in columns, columns  # control: a column already there
    assert "damage_dealt" not in columns  # control: that is the report's name


def test_the_fixture_insert_matches_its_own_column_count():
    """The INSERT is positional, so widening the DDL without widening every
    tuple slides `score` into `damage`. MySQL rejects it -- in the one lane
    that runs a real server."""
    body = FIXTURE.read_text(encoding="utf-8").split(
        "INSERT INTO ktp_match_stats VALUES", 1)[1].split(";", 1)[0]
    tuples = re.findall(r"\('phase-a-contract-TEST'[^)]*\)", body)
    assert len(tuples) == 12, len(tuples)
    widths = {t.count(",") + 1 for t in tuples}
    assert widths == {len(_match_stats_ddl())}, widths


# --- a cross-tagged ledger row stays out of the box score --------------------

def _damage_join() -> str:
    sql = (REPO / "sql" / "analytics" / "player_match_fact.sql").read_text(
        encoding="utf-8")
    block = sql.split("LEFT JOIN ktp_damage_events d", 1)[1].split(
        "LEFT JOIN roster attacker", 1)[0]
    return re.sub(r"--[^\n]*", "", block)


def test_the_box_score_defers_to_the_producer_match():
    """`producer_match_id` is authoritative wherever it is set, so a ledger row
    tagged for another match must not reach this match's damage columns. The
    integration lane proves it against MySQL; this pins it in the cheap lane."""
    join = " ".join(_damage_join().split())
    assert ("d.producer_match_id IS NULL OR "
            "BINARY d.producer_match_id = BINARY d.match_id") in join, join
    # Control: the clause sits in the damage join, not merely somewhere in the file.
    assert "d.match_id = r.match_id" in join
