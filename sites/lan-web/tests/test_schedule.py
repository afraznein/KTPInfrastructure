"""Unit tests for the Saturday group schedules (10/11/12 teams)."""
from app import schedule as S


def _pairs(sched):
    return [tuple(sorted(p)) for rnd in sched for p in rnd]


def test_no_repeat_pairings():
    for n, sched in S.SCHEDULES.items():
        pairs = _pairs(sched)
        assert len(pairs) == len(set(pairs)), f"repeat pairing in {n}-team schedule"


def test_round_match_counts():
    assert all(len(r) == 5 for r in S.SCHEDULE_10)
    assert all(len(r) == 5 for r in S.SCHEDULE_11)   # odd field: 5 matches + 1 bye
    assert all(len(r) == 6 for r in S.SCHEDULE_12)


def test_six_rounds_each():
    assert all(len(sched) == 6 for sched in S.SCHEDULES.values())


def test_seeds_fully_covered():
    for n, sched in S.SCHEDULES.items():
        seen = {x for rnd in sched for p in rnd for x in p}
        assert seen == set(range(1, n + 1))


def test_one_v_two_closes_the_day():
    for n, sched in S.SCHEDULES.items():
        assert (1, 2) in _pairs([sched[-1]]), f"{n}-team schedule must end on 1v2"


def test_top_four_isolated_until_round_four():
    for n, sched in S.SCHEDULES.items():
        for ri, rnd in enumerate(sched[:3], 1):     # rounds 1-3
            for a, b in rnd:
                assert not (a <= 4 and b <= 4), f"top-4 met in {n}-team R{ri}"


def test_11_team_byes_rotate():
    byes = []
    for rnd in S.SCHEDULE_11:
        present = {x for p in rnd for x in p}
        missing = set(range(1, 12)) - present
        assert len(missing) == 1                     # exactly one rests per round
        byes.append(missing.pop())
    assert len(set(byes)) == 6                        # six distinct teams rest


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
