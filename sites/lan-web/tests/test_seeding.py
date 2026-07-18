"""Unit tests for the weighted peer-ranking algorithm (pure, no DB)."""
from app.seeding import compute_seeds


def test_unanimous_ranking_is_identity():
    # everyone agrees 1>2>3>4; each ranks the other three in order
    teams = [1, 2, 3, 4]
    ballots = {}
    for v in teams:
        others = [t for t in teams if t != v]
        ballots[v] = {t: i + 1 for i, t in enumerate(sorted(others))}
    standing, score, weight = compute_seeds(ballots, teams)
    assert standing == [1, 2, 3, 4]


def test_weighting_breaks_a_split_toward_stronger_voters():
    # 3 teams; team 1 clearly strongest (ranked 1st by all).
    # 2 and 3 are split, but the strongest voter (team 1) favors team 2.
    teams = [1, 2, 3]
    ballots = {
        1: {2: 1, 3: 2},   # team 1 (heaviest ballot) says 2 > 3
        2: {1: 1, 3: 2},
        3: {1: 1, 2: 2},   # team 3 says 1 > 2 ... agrees 2 ahead of itself implicitly
    }
    standing, score, weight = compute_seeds(ballots, teams)
    assert standing[0] == 1
    assert standing == [1, 2, 3]


def test_handles_missing_ballot():
    # team 4 never submitted; algorithm still ranks everyone, no crash
    teams = [1, 2, 3, 4]
    ballots = {
        1: {2: 1, 3: 2, 4: 3},
        2: {1: 1, 3: 2, 4: 3},
        3: {1: 1, 2: 2, 4: 3},
    }
    standing, score, weight = compute_seeds(ballots, teams)
    assert set(standing) == {1, 2, 3, 4}
    assert standing[0] == 1
    assert standing[-1] == 4  # consistently ranked worst


def test_deterministic():
    teams = [1, 2, 3, 4, 5]
    ballots = {v: {t: i + 1 for i, t in enumerate(t2 for t2 in teams if t2 != v)} for v in teams}
    a = compute_seeds(ballots, teams)[0]
    b = compute_seeds(ballots, teams)[0]
    assert a == b


if __name__ == "__main__":
    import sys
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in funcs:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(funcs) - failed}/{len(funcs)} passed")
    sys.exit(1 if failed else 0)
