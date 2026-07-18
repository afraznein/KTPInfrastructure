"""Unit tests for the standings tiebreak ladder."""
from app.standings import compute_standings

TEAMS = [{"id": i, "name": f"T{i}", "tag": f"T{i}", "seed": i} for i in range(1, 5)]


def _m(a, b, sa, sb):
    return {"team_a_id": a, "team_b_id": b, "score_a": sa, "score_b": sb, "status": "final"}


def test_wins_order():
    # 1 beats everyone, 4 loses to everyone
    matches = [_m(1, 2, 5, 0), _m(1, 3, 5, 0), _m(1, 4, 5, 0),
               _m(2, 3, 5, 0), _m(2, 4, 5, 0), _m(3, 4, 5, 0)]
    s = compute_standings(TEAMS, matches)
    assert [r["team"]["id"] for r in s] == [1, 2, 3, 4]
    assert s[0]["wins"] == 3 and s[-1]["wins"] == 0


def test_head_to_head_breaks_equal_wins():
    # 2 and 3 both finish 1-1; head-to-head: 3 beat 2 -> 3 ranks above 2
    matches = [_m(1, 2, 5, 0), _m(1, 3, 5, 0),   # 1 wins both
               _m(2, 3, 0, 5),                    # 3 beats 2
               _m(2, 4, 5, 0), _m(3, 4, 5, 0)]    # 2 and 3 both beat 4
    s = compute_standings(TEAMS, matches)
    ids = [r["team"]["id"] for r in s]
    assert ids[0] == 1
    assert ids.index(3) < ids.index(2)  # head-to-head winner ranks higher


def test_pending_matches_ignored():
    matches = [_m(1, 2, 5, 0), {"team_a_id": 3, "team_b_id": 4, "score_a": None,
                                "score_b": None, "status": "pending"}]
    s = compute_standings(TEAMS, matches)
    assert all("rank" in r for r in s)
    assert s[0]["team"]["id"] == 1


def test_differential_when_no_h2h():
    # 2 and 3 never played each other, equal wins -> differential decides
    matches = [_m(1, 2, 5, 0), _m(1, 3, 5, 0),
               _m(2, 4, 5, 0), _m(3, 4, 5, 4)]  # team 2 bigger margin vs 4
    s = compute_standings(TEAMS, matches)
    ids = [r["team"]["id"] for r in s]
    assert ids.index(2) < ids.index(3)


def test_win_pct_beats_raw_win_tie_on_unequal_games():
    # Odd-field case: a team that played fewer games shouldn't be out-ranked by
    # one with the same raw wins but a worse record. Team 1 is 1-0 (100%); team 2
    # is 1-1 (50%); both have 1 raw win, but 1 must rank above 2.
    teams = [{"id": i, "name": f"T{i}", "tag": None, "seed": i} for i in (1, 2, 3)]
    matches = [_m(1, 3, 5, 0),                 # team 1: 1-0  (played 1)
               _m(2, 3, 5, 0), _m(2, 3, 0, 5)]  # team 2: 1-1 (played 2), team 3: 1-2
    s = compute_standings(teams, matches)
    ids = [r["team"]["id"] for r in s]
    assert ids == [1, 2, 3]
    assert s[0]["played"] == 1 and s[1]["played"] == 2


if __name__ == "__main__":
    import sys
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in funcs:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(funcs) - failed}/{len(funcs)} passed")
    sys.exit(1 if failed else 0)
