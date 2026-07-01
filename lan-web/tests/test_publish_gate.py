"""Unit tests for the publish-gate reveal logic (pure, no DB)."""
from app.seeding import reveal_poll_results, reveal_schedule


# ── poll results: blind while open, staff-review after close ──────────────
def test_open_poll_hidden_from_everyone_on_a_team():
    # neutral staff may watch it fill in; anyone on a competing team may not
    assert reveal_poll_results(is_admin=True, poll_open=True, published=False) is True
    assert reveal_poll_results(is_admin=True, poll_open=True, published=False,
                               viewer_on_team=True) is False   # staff-captain: blinded
    assert reveal_poll_results(is_admin=False, poll_open=True, published=False) is False


def test_open_poll_publish_flag_does_not_leak():
    # publishing early can't reveal an open poll to the public
    assert reveal_poll_results(is_admin=False, poll_open=True, published=True) is False
    assert reveal_poll_results(is_admin=True, poll_open=True, published=True,
                               viewer_on_team=True) is False


def test_closed_poll_staff_see_public_waits_for_publish():
    # closed + unpublished: staff yes (even staff-captains), public no
    assert reveal_poll_results(is_admin=True, poll_open=False, published=False) is True
    assert reveal_poll_results(is_admin=True, poll_open=False, published=False,
                               viewer_on_team=True) is True
    assert reveal_poll_results(is_admin=False, poll_open=False, published=False) is False
    # closed + published: everyone sees
    assert reveal_poll_results(is_admin=False, poll_open=False, published=True) is True


# ── schedule / bracket: staff-only until published ────────────────────────
def test_schedule_hidden_until_published():
    assert reveal_schedule(is_admin=True, published=False) is True    # staff review
    assert reveal_schedule(is_admin=False, published=False) is False  # public waits
    assert reveal_schedule(is_admin=False, published=True) is True    # published


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
