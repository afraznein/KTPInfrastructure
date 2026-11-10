"""Death-group link availability: a missing link reads unavailable, never zero."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import match_analytics, match_readiness
from tests.unit.test_match_readiness_failures import (
    MATCH_ID, finding, healthy_tables, validate,
)

SQL = Path(__file__).resolve().parents[2] / "sql" / "analytics" / "death_group_link_fact.sql"


def linked_tables(*, life_seq="5", frag_seq="9", assist_life="5", assist_frag="9",
                  frag_life="5"):
    """One non-teamkill death: life-end 5, frag 9, one assist naming both."""
    tables = healthy_tables()
    frag = tables["hlstats_Events_Frags"][0]
    frag.update({"serverId": "3", "producer_match_id": MATCH_ID, "producer_half": "1",
                 "producer_sequence": frag_seq, "causal_parent_life_sequence": frag_life})
    tables["ktp_life_events"] = [{
        "id": "1", "server_id": "3", "match_id": MATCH_ID, "half": "1",
        "boundary_kind": "end", "reason": "death", "producer_sequence": life_seq,
    }]
    tables["ktp_assist_events"] = [{
        "id": "1", "server_id": "3", "match_id": MATCH_ID, "half": "1",
        "producer_sequence": "1", "causal_parent_life_sequence": assist_life,
        "causal_parent_frag_sequence": assist_frag,
    }]
    return tables


def evidence(report):
    check = finding(report, "death_group_link_resolution")
    return {"level": check["level"], **check["evidence"]}


def eligibility(report):
    return report["metric_eligibility"]["metrics"]["death_group"]


def test_an_archive_without_links_is_unavailable_not_partial(monkeypatch, tmp_path):
    report = validate(monkeypatch, tmp_path, healthy_tables())
    assert report["status"] == "PASS"
    assert "death_group_link_resolution" not in {c["code"] for c in report["checks"]}
    assert eligibility(report)["status"] == "unavailable"
    assert eligibility(report)["blocking_checks"] == ["death_group_link_resolution"]
    assert report["inventory"]["death_group_links"] == 0


def test_resolving_links_make_death_group_available(monkeypatch, tmp_path):
    report = validate(monkeypatch, tmp_path, linked_tables())
    check = evidence(report)
    assert (check["level"], check["linked"], check["resolved"]) == ("PASS", 3, 3)
    assert eligibility(report)["status"] == "available"


def test_a_dropped_frag_marker_is_no_parent_not_a_broken_link(monkeypatch, tmp_path):
    report = validate(monkeypatch, tmp_path, linked_tables(assist_frag=None))
    check = evidence(report)
    assert (check["level"], check["linked"], check["unresolved"]) == ("PASS", 2, 0)


@pytest.mark.parametrize("override", [
    {"assist_life": "6"},
    {"assist_frag": "5"},  # the life-end's number in the frag space resolves nothing
    {"frag_life": "9"},    # the frag's own number in the life space likewise
])
def test_a_link_that_names_nothing_fails_the_check(monkeypatch, tmp_path, override):
    report = validate(monkeypatch, tmp_path, linked_tables(**override))
    check = evidence(report)
    assert (check["level"], check["unresolved"]) == ("FAIL", 1)
    assert eligibility(report)["status"] == "unavailable"


def test_a_link_resolves_only_inside_its_own_half_and_server(monkeypatch, tmp_path):
    tables = linked_tables()
    tables["ktp_life_events"][0]["half"] = "2"
    tables["hlstats_Events_Frags"][0]["serverId"] = "4"
    check = evidence(validate(monkeypatch, tmp_path, tables))
    assert (check["linked"], check["resolved"]) == (3, 0)


def fact(half, stream, events, life_linked, life_resolved, frag_linked=None,
         frag_resolved=None):
    return {"half": half, "stream": stream, "events": events,
            "life_linked": life_linked, "life_resolved": life_resolved,
            "frag_linked": frag_linked, "frag_resolved": frag_resolved}


def test_missing_columns_read_unavailable_with_no_numbers():
    block = match_analytics.build_death_group([], available=False)
    assert block["status"] == "unavailable" and block["halves"] == []
    assert "assists" not in str(block["halves"])


def test_a_half_without_links_carries_no_counts():
    block = match_analytics.build_death_group([
        fact(1, "assist", 4, 0, 0, 0, 0), fact(1, "frag", 20, 0, 0),
        fact(2, "assist", 3, 3, 3, 2, 2), fact(2, "frag", 18, 18, 18),
    ], available=True)
    first, second = block["halves"]
    assert block["status"] == "partial"
    assert first == {"half": 1, "status": "unavailable",
                     "reason": "no causal link was recorded in this half"}
    assert second["status"] == "available" and second["unresolved_links"] == 0
    assert (second["assists_frag_linked"], second["frags_life_resolved"]) == (2, 18)


def test_an_unresolved_link_makes_the_half_partial():
    block = match_analytics.build_death_group([
        fact(1, "assist", 2, 2, 1, 1, 1), fact(1, "frag", 5, 5, 5),
    ], available=True)
    assert block["status"] == "partial"
    assert block["halves"][0]["unresolved_links"] == 1


def test_every_half_linked_and_resolved_is_available():
    block = match_analytics.build_death_group([
        fact(1, "frag", 5, 5, 5), fact(2, "frag", 6, 6, 6),
    ], available=True)
    assert block["status"] == "available"
    assert [h["half"] for h in block["halves"]] == [1, 2]


def test_the_query_is_read_only_counts_on_the_typed_key():
    query = match_analytics.read_query("death_group_link_fact.sql", MATCH_ID)
    lowered = query.lower()
    for column in ("server_id", "serverid", "boundary_kind = 'end'",
                   "producer_sequence = ae.causal_parent_life_sequence",
                   "producer_sequence = ae.causal_parent_frag_sequence",
                   "producer_sequence = f.causal_parent_life_sequence"):
        assert column in lowered, column
    for forbidden in ("player_name", "steam_id", "insert", "update ", "delete"):
        assert forbidden not in lowered, forbidden
    assert SQL.read_bytes().count(b"\r") == 0
