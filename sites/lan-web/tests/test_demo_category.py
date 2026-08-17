"""Draft / scrim / 12-man demos: they belong to the weekend, not to a match."""
from app import demos
from app.routes.demo_routes import _parse_match


def test_a_match_value_still_parses_as_before():
    assert _parse_match("sat:12") == (12, None, "match")
    assert _parse_match("bkt:QF1") == (None, "QF1", "match")


def test_generic_values_carry_their_category():
    assert _parse_match("gen:draft") == (None, None, "draft")
    assert _parse_match("gen:scrim") == (None, None, "scrim")
    assert _parse_match("gen:12man") == (None, None, "12man")


def test_an_unknown_category_falls_back_rather_than_reaching_the_enum():
    """The column is an ENUM under STRICT_TRANS_TABLES, so an unwhitelisted
    value would error the insert rather than being stored."""
    for bad in ["gen:", "gen:nope", "gen:draft; DROP", "gen:MATCH", "garbage", ""]:
        assert _parse_match(bad) == (None, None, "match"), bad


def test_every_offered_option_round_trips():
    """Control: the dropdown cannot offer a value the parser would discard."""
    for opt in demos.generic_options():
        assert _parse_match(opt["value"])[2] in demos.GENERIC


def test_generic_demos_are_labelled_by_category(monkeypatch):
    monkeypatch.setattr(demos.db, "query_all",
                        lambda *a, **k: [{"schedule_id": None, "bracket_mkey": None,
                                          "category": "draft"}])
    monkeypatch.setattr(demos, "label_maps", lambda: ({}, {}))
    assert demos.listing()[0]["match_label"] == "Draft night"


def test_an_untagged_demo_still_has_no_label(monkeypatch):
    """Control for the test above — 'match' must not invent a label."""
    monkeypatch.setattr(demos.db, "query_all",
                        lambda *a, **k: [{"schedule_id": None, "bracket_mkey": None,
                                          "category": "match"}])
    monkeypatch.setattr(demos, "label_maps", lambda: ({}, {}))
    assert demos.listing()[0]["match_label"] is None
