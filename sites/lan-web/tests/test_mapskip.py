"""Unit tests for the map-skip plurality tally (pure, no DB)."""
from app.mapskip import tally

POOL = ["Harrington", "Lennon", "Anzio", "Saints", "Thunder2", "Railroad2", "Armory"]


def test_clear_winner_leads():
    ballots = {1: "Anzio", 2: "Anzio", 3: "Anzio", 4: "Saints", 5: "Lennon"}
    ordered, counts = tally(ballots, POOL)
    assert ordered[0] == "Anzio"
    assert counts["Anzio"] == 3
    assert counts["Saints"] == 1
    assert counts["Harrington"] == 0


def test_tie_breaks_to_pool_order():
    # Lennon and Anzio tie at 2; Lennon comes first in the pool, so it leads.
    ballots = {1: "Lennon", 2: "Lennon", 3: "Anzio", 4: "Anzio"}
    ordered, counts = tally(ballots, POOL)
    assert counts["Lennon"] == counts["Anzio"] == 2
    assert ordered.index("Lennon") < ordered.index("Anzio")


def test_empty_ballots_all_zero():
    ordered, counts = tally({}, POOL)
    assert set(ordered) == set(POOL)
    assert all(counts[m] == 0 for m in POOL)


def test_off_pool_vote_ignored():
    ballots = {1: "Halle", 2: "Anzio"}  # Halle is no longer in the pool
    ordered, counts = tally(ballots, POOL)
    assert "Halle" not in counts
    assert counts["Anzio"] == 1
    assert ordered[0] == "Anzio"


def test_deterministic():
    ballots = {1: "Armory", 2: "Saints", 3: "Saints", 4: "Armory"}
    assert tally(ballots, POOL) == tally(ballots, POOL)


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
