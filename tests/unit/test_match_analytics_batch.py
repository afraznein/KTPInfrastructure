from scripts.match_analytics import tsv_rows
from scripts.match_analytics_batch import choose_representatives, safe_report_name


def report(match_id, roster=12, frags=10, cache=12, halves=2, map_name="dod_anzio"):
    return {
        "match_id": match_id,
        "match": {"map_name": map_name, "halves_played": halves},
        "source_inventory": {
            "roster_players": roster,
            "frags": frags,
            "cached_player_totals": cache,
        },
    }


def test_unsafe_match_id_gets_stable_safe_filename():
    value = safe_report_name(") (map dod_harrington")
    assert value == "___map_dod_harrington-826e8149"
    assert ")" not in value and " " not in value


def test_mysql_tsv_quotes_are_literal_identifier_data():
    output = 'match_id\n") (map "dod_harrington\n'
    assert tsv_rows(output) == [{"match_id": '") (map "dod_harrington'}]


def test_representatives_do_not_hide_malformed_or_valid_missing_roster():
    selected = choose_representatives([
        report(") (map dod_harrington", roster=0, frags=0, cache=0, halves=0),
        report("1785526923-KTP5", roster=0, frags=0, cache=0, halves=1),
        report("1785527247-KTP2"),
    ])
    assert selected["malformed_or_orphan_id"] == ") (map dod_harrington"
    assert selected["missing_roster"] == "1785526923-KTP5"
    assert selected["complete:dod_anzio"] == "1785527247-KTP2"


def test_test_match_id_is_not_labeled_malformed():
    selected = choose_representatives([report("1786978609-TEST", halves=1)])
    assert selected["test_match_id"] == "1786978609-TEST"
    assert "malformed_or_orphan_id" not in selected
