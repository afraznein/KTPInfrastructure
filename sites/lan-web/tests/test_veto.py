"""Unit tests for the map-veto step sequence (BO1 + BO3)."""
from app.veto import sequence


def test_bo3_sequence_pool8():
    s = sequence(8, 3)
    acts = [x["action"] for x in s]
    assert acts.count("ban") == 5      # pool - 3
    assert acts.count("pick") == 2
    assert acts.count("decider") == 1
    assert s[0] == {"actor": "TS", "action": "ban"}        # TS opens
    assert s[-1] == {"actor": "TS", "action": "decider"}   # TS controls the decider side


def test_bo1_sequence_pool8():
    s = sequence(8, 1)
    acts = [x["action"] for x in s]
    assert acts.count("ban") == 7      # pool - 1, down to one map
    assert acts.count("pick") == 0
    assert acts.count("decider") == 1
    assert s[0]["actor"] == "TS"                            # top seed bans first
    assert s[-1] == {"actor": "LS", "action": "decider"}   # lower seed picks the side
    ban_actors = [x["actor"] for x in s if x["action"] == "ban"]
    assert ban_actors == ["TS", "LS", "TS", "LS", "TS", "LS", "TS"]   # strict alternation


def test_bo1_ban_count_scales_with_pool():
    for pool in (4, 6, 7, 8):
        s = sequence(pool, 1)
        assert sum(1 for x in s if x["action"] == "ban") == pool - 1
        assert s[-1]["action"] == "decider"


def test_default_is_bo3():
    assert sequence(8) == sequence(8, 3)


def test_too_small_pool_yields_no_steps():
    assert sequence(2, 3) == []        # need at least 3 maps for a BO3
    assert sequence(0, 1) == []


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
