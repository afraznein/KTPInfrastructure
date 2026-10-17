"""Winner labels from HLTV demos: derivation, ledger rows, importer CLI.

Fixtures are dod-tools v0.10.0 JSON reports captured from real demos (the 9
official S10 matches of 2026-09-13 plus 5 12man/scrim test matches), so the
suite needs neither a demo nor the parser binary. Expected totals for the
official matches are ktpleague.gg's admin-entered scores, checked 2026-09-17.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from scripts import demo_team_score as dts
from scripts import import_demo_team_score as cli

FIXTURES = Path(__file__).parents[1] / "fixtures" / "demo_team_score"
SHA = json.loads((FIXTURES / "DEMO_SHA256SUMS.json").read_text(encoding="utf-8"))

# ktpleague.gg /schedule + /stats/matches/<id>, 2026-09-17. Slot 1 = Allies in half 1.
SITE_TOTALS = {
    "1789326428-NY1": {1: 273, 2: 25},    # GSKILL 273-25 RenameD*Gaming; halves 142-12, 131-13
    "1789326628-NY5": {1: 79, 2: 117},    # MACRON EXPLOSION 79-117 Rifle Nades
    "1789326741-NY3": {1: 130, 2: 70},    # IcyHot 130-70 -revo
    "1789326983-NY4": {1: 24, 2: 208},    # UnderDog 24-208 Team Mushrooms
    "1789328375-NY2": {1: 144, 2: 108},   # Silver Backs 144-108 Team GreenLand
    "1789348148-ATL4": {1: 128, 2: 58},   # ClanX 128-58 Price is Right
    "1789348175-ATL3": {1: 134, 2: 101},  # Very Handsome Seniors 134-101 Riviu
    "1789348403-ATL2": {1: 62, 2: 138},   # Hot Mess Express 62-138 Let me win
    "1789351895-DAL5": {1: 321, 2: 375},  # week-2 match played early; not on the week-1 schedule page
}


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def halves_for(prefix: str) -> list[dts.HalfDemo]:
    out = []
    for path in sorted(FIXTURES.glob(f"{prefix}_h*.dem.json")):
        name = path.name[:-len(".json")]
        d = dts.parse_demo_name(name)
        out.append(dts.half_from_report(load(name), name, file_sha256=bytes.fromhex(SHA[name]),
                                        archive_path=f"demos/{d.server}/{d.type}/{name}"))
    return out


def all_labels() -> list[dts.MatchLabel]:
    reports = []
    for path in sorted(FIXTURES.glob("*.dem.json")):
        name = path.name[:-len(".json")]
        d = dts.parse_demo_name(name)
        reports.append((name, load(name), bytes.fromhex(SHA[name]), f"demos/{d.server}/{d.type}/{name}"))
    return dts.labels_from_reports(reports)


# ---------------------------------------------------------------- names

@pytest.mark.parametrize("name,expect", [
    ("ktp_1789326428-NY1_h1-2609131459-dod_thunder2.dem", ("ktp", "1789326428-NY1", 1, "2609131459", "dod_thunder2", None)),
    ("12man_1.3-6744-ATL1_h2-2609070026-dod_armory_b6.dem", ("12man", "1.3-6744-ATL1", 2, "2609070026", "dod_armory_b6", None)),
    ("scrim_1788746783-CHI1_h1-2609062203-dod_lennon5_b1.dem", ("scrim", "1788746783-CHI1", 1, "2609062203", "dod_lennon5_b1", None)),
    ("12man_1.3-6069-CHI1_h1-2606092048-dod_armory_b6_part2.dem", ("12man", "1.3-6069-CHI1", 1, "2606092048", "dod_armory_b6", 2)),
])
def test_parse_demo_name(name, expect):
    d = dts.parse_demo_name(name)
    assert (d.type, d.match_id, d.half, d.stamp, d.map_name, d.part) == expect


def test_parse_demo_name_rejects_unlabelled():
    with pytest.raises(dts.DemoLabelError):
        dts.parse_demo_name("auto_20260913-1459-dod_thunder2.dem")


def test_match_type_and_retention():
    assert dts.parse_demo_name("ktp_1789326428-NY1_h1-2609131459-dod_thunder2.dem").match_type == 0
    assert dts.parse_demo_name("scrim_1788746783-CHI1_h1-2609062203-dod_lennon5_b1.dem").match_type == 1
    assert dts.parse_demo_name("12man_1.3-6744-ATL1_h1-2609070000-dod_armory_b6.dem").match_type == 2
    assert dts.retention_class(0, "1789326428-NY1") == "retained"
    assert dts.retention_class(1, "1.3-6744-ATL1") == "ephemeral-14d"


def test_demo_label_map_agrees_with_the_report_scope_sets():
    """The map is a transcription of KTPMatchHandler's enum, and a transcription needs a
    check that is not another transcription. These two sets are derived from the same enum
    independently, so a swapped pair disagrees with them -- as the previous map did, both ways.
    """
    from scripts.report_scope import (
        MATCH_TYPE_BY_DEMO_LABEL, OFFICIAL_MATCH_TYPES, SHADOW_MATCH_TYPES)
    m = MATCH_TYPE_BY_DEMO_LABEL
    assert m["ktp"] in OFFICIAL_MATCH_TYPES
    assert m["12man"] in SHADOW_MATCH_TYPES          # 12man is the shadow-report type (2)
    assert m["scrim"] not in SHADOW_MATCH_TYPES      # scrims are deliberately out of scope
    assert m["scrim"] not in OFFICIAL_MATCH_TYPES
    assert m["draft"] not in OFFICIAL_MATCH_TYPES + SHADOW_MATCH_TYPES
    assert len(set(m.values())) == len(m), "two labels share an id"
    # Overtime labels are absent on purpose: an unknown label must raise, not guess.
    assert "ktpot" not in m and "draftot" not in m


def test_an_unlabelled_type_raises_rather_than_guessing():
    with pytest.raises(dts.DemoLabelError):
        dts.parse_demo_name("ktpot_1789326428-NY1_h1-2609131459-dod_thunder2.dem").match_type

def test_started_at_from_stamp():
    assert dts.parse_demo_name("ktp_1789326428-NY1_h1-2609131459-dod_thunder2.dem").started_at == "2026-09-13 14:59:00.000"


# ---------------------------------------------------------------- one demo

def test_official_demo_excludes_spectators_and_keeps_six_a_side():
    h = halves_for("ktp_1789326428-NY1")[0]
    assert len(h.allies_roster) == 6 and len(h.axis_roster) == 6
    assert h.spectators, "official S10 demos carry casters/admins as spectators"
    assert all(a.isdigit() for a in h.allies_roster + h.axis_roster), "rosters are account numbers, not full ids"


def test_half_from_report_rejects_missing_score():
    with pytest.raises(dts.DemoLabelError):
        dts.half_from_report({"teams": {"allies": 1}, "players": []},
                             "ktp_1789326428-NY1_h1-2609131459-dod_thunder2.dem",
                             file_sha256=b"\0" * 32, archive_path="x")


# ---------------------------------------------------------------- labels

def test_half_two_is_cumulative_and_half_scores_are_differenced():
    label = dts.label_match(halves_for("ktp_1789326428-NY1"))
    h1, h2 = label.halves
    assert (h1.demo.allies_score, h1.demo.axis_score) == (142, 12)
    assert (h2.demo.allies_score, h2.demo.axis_score) == (25, 273), "the h2 demo reports match totals"
    assert h1.half_score == {1: 142, 2: 12}
    assert h2.half_score == {1: 131, 2: 13}, "site shows halves 142-12 / 131-13"
    assert (h1.allies_slot, h1.axis_slot) == (1, 2)
    assert (h2.allies_slot, h2.axis_slot) == (2, 1), "sides swap at half"
    assert (h1.winner_team, h2.winner_team) == (1, 2), "slot 1 won both halves: Allies in h1, Axis in h2"
    assert label.totals == {1: 273, 2: 25} and label.winner_slot == 1


def test_official_totals_match_the_site():
    labels = {l.match_id: l for l in all_labels() if l.match_type == 0}
    assert set(labels) == set(SITE_TOTALS)
    for mid, expect in SITE_TOTALS.items():
        assert labels[mid].totals == expect, mid
        assert labels[mid].side_swap_seen, mid


def test_split_halves_are_read_correctly():
    # NY5: slot 1 won h1 52-48, slot 2 won h2 69-27; match to slot 2, 117-79.
    label = dts.label_match(halves_for("ktp_1789326628-NY5"))
    assert [h.winner_slot for h in label.halves] == [1, 2]
    assert label.winner_slot == 2


def test_carryover_invariant_holds_for_every_match():
    for label in all_labels():
        rows, manifest = dts.build_rows(label, manifest_sha256=b"\1" * 32)
        by = {}
        for r in rows:
            by.setdefault(r.half, {})[r.observation_kind] = r
        assert by[1]["baseline"].allies_score == 0 and by[1]["baseline"].axis_score == 0
        f1, b2 = by[1]["final"], by[2]["baseline"]
        slot_f1 = {f1.allies_team_id: f1.allies_score, f1.axis_team_id: f1.axis_score}
        slot_b2 = {b2.allies_team_id: b2.allies_score, b2.axis_team_id: b2.axis_score}
        assert slot_f1 == slot_b2, f"{label.match_id}: h2 must open at h1's final, by slot"
        assert manifest.terminal_half == 2 and manifest.event_count == len(rows) == 4


def test_score_regression_is_an_error():
    h1, h2 = halves_for("ktp_1789326428-NY1")
    broken = dts.HalfDemo(**{**h2.__dict__, "allies_score": 0, "axis_score": 0})
    with pytest.raises(dts.DemoLabelError, match="regressed"):
        dts.label_match([h1, broken])


def test_missing_half_one_is_an_error():
    _, h2 = halves_for("ktp_1789326428-NY1")
    with pytest.raises(dts.DemoLabelError, match="half 1 missing"):
        dts.label_match([h2])


def test_rows_are_shaped_for_the_ledger():
    label = dts.label_match(halves_for("ktp_1789326428-NY1"))
    rows, manifest = dts.build_rows(label, manifest_sha256=b"\2" * 32)
    assert len(rows) == 4
    for r in rows:
        assert r.source == dts.SOURCE and r.source_version == dts.SOURCE_VERSION
        assert r.tick_seconds == Decimal(0)
        assert {r.allies_team_id, r.axis_team_id} == {1, 2}
        assert r.retention_class == "retained"
        raw = json.loads(r.raw_event_json)
        assert raw["producer"] == dts.PRODUCER and raw["tool"].startswith("dod-tools ")
        assert raw["demo"].endswith(".dem")
    finals = [r for r in rows if r.observation_kind == "final"]
    assert [json.loads(r.raw_event_json)["winner_team"] for r in finals] == [1, 2]
    assert manifest.match_end_allies_score == 25 and manifest.match_end_axis_score == 273
    assert manifest.events_file_sha256 == label.halves[0].demo.file_sha256
    assert manifest.metadata_file_sha256 == label.halves[1].demo.file_sha256


# ---------------------------------------------------------------- SQL

def test_import_sql_shape():
    sql, rows, manifests = dts.sql_for_labels([l for l in all_labels() if l.match_type == 0])
    assert len(rows) == 36 and len(manifests) == 9
    assert f"GET_LOCK('{dts.LEDGER_LOCK}',30)" in sql and f"RELEASE_LOCK('{dts.LEDGER_LOCK}')" in sql
    assert "START TRANSACTION;" in sql and "COMMIT;" in sql
    assert "CREATE TEMPORARY TABLE `ktp_demo_ts_manifest_stage`" in sql
    assert "CREATE TEMPORARY TABLE `ktp_demo_ts_row_stage`" in sql
    assert "INSERT INTO `ktp_team_score_ingest_manifests`" in sql
    assert "INSERT INTO `ktp_team_score_observations`" in sql
    assert "ON DUPLICATE KEY UPDATE id=id" in sql
    assert "ON DUPLICATE KEY UPDATE `ktp_team_score_ingest_manifests`.`match_id`" in sql
    # the spelling that cannot execute -- guards the 1052 regression, not the wording
    assert "ON DUPLICATE KEY UPDATE match_id=match_id" not in sql
    assert "KTPHudObserver" not in sql, "never write under the HUD producer"
    prod = dts._sql_text(dts.PRODUCER)
    assert sql.count(prod) >= 36 + 9, "every row and manifest carries our producer"
    assert f"m.producer<>{prod}" in sql, "another producer's match is skipped"
    assert "KTP_DEMO_TEAM_SCORE_RESULT" in sql and "lock_acquired" in sql


def test_import_sql_empty():
    assert dts.build_import_sql([], []).startswith("SELECT 'KTP_DEMO_TEAM_SCORE_RESULT'")


# ---------------------------------------------------------------- CLI

def test_cli_sql_out_without_binary(tmp_path, monkeypatch):
    """Drive the CLI end to end with the parser stubbed by fixtures."""
    demos = []
    for name in ("ktp_1789326428-NY1_h1-2609131459-dod_thunder2.dem", "ktp_1789326428-NY1_h2-2609131529-dod_thunder2.dem"):
        p = tmp_path / "NY1" / "ktp" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"not a demo")
        demos.append(p)
    monkeypatch.setattr(cli, "run_dod_tools", lambda _cli, demo: load(demo.name))
    out = tmp_path / "out.sql"
    rc = cli.main(["--dod-tools", str(tmp_path / "fake-cli"), "--demos-root", str(tmp_path),
                   "--types", "ktp", "--sql-out", str(out)])
    assert rc == 0
    sql = out.read_text(encoding="utf-8")
    mid = dts._sql_text("1789326428-NY1")
    assert sql.count(f"({mid},") == 4 + 1, "4 observation rows + 1 manifest for the match"


def test_cli_refuses_apply_without_database(tmp_path):
    assert cli.main(["--dod-tools", "x", "--apply"]) == 2


def test_cli_needs_an_output(tmp_path):
    assert cli.main(["--dod-tools", "x", "--demos-root", str(tmp_path)]) == 2
