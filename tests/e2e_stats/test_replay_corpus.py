from copy import deepcopy

from scripts.replay_corpus import compare


def _report():
    return {
        "emitted": {"kills": 10, "assist": 2, "cap_break": 1, "suicide": 0},
        "rows": {
            "frags": 10,
            "players": 12,
            "suicides": 0,
            "assist": {"pa": 0, "ppa": 2},
            "cap_break": {"pa": 1, "ppa": 0},
            "pa_rows_total": 100,
            "ppa_rows_total": 200,
        },
    }


def test_compare_ignores_unrelated_action_rows():
    want = _report()
    got = deepcopy(want)
    got["rows"]["pa_rows_total"] += 50
    got["rows"]["ppa_rows_total"] += 75

    assert compare("match.log.gz", got, want) == []


def test_compare_detects_scoped_action_regression():
    want = _report()
    got = deepcopy(want)
    got["rows"]["cap_break"]["pa"] = 0

    assert compare("match.log.gz", got, want) == [
        "match.log.gz: rows.cap_break.pa 1 -> 0"
    ]
