from . import own_weapon_scenario as ow

BEGIN = "[OW] BEGIN a=3 aname=BotA b=5 bname=BotB wpn=kar"
LINE = '"BotB<5><BOT><Axis>" triggered "own_weapon_kill" against "BotA<3><BOT><Axis>" with "kar" (owner_drop "death") (since_drop_s "1.3")'


def body(*lines, mode="real"):
    return "\n".join([BEGIN, *lines, f"[OW] END mode={mode}"])


def test_real_pickup_and_one_line_is_ok():
    v = ow.judge(body("[OW] FWD id=5 wpn=6 value=0", "[OW] FWD id=5 wpn=10 value=1", LINE))
    assert v["status"] == "ok", v


def test_synthetic_pickup_is_not_exercised_even_with_the_right_line():
    v = ow.judge(body(LINE, mode="synthetic"))
    assert v["status"] == "not_exercised" and "ledger ok" in v["detail"]


def test_missing_line_is_a_pipeline_failure():
    v = ow.judge(body("[OW] FWD id=5 wpn=10 value=1"))
    assert v["status"] == "pipeline" and "saw 0" in v["detail"]


def test_two_lines_is_a_pipeline_failure():
    assert ow.judge(body(LINE, LINE))["status"] == "pipeline"


def test_wrong_owner_is_a_pipeline_failure():
    v = ow.judge(body(LINE.replace('against "BotA', 'against "BotC')))
    assert v["status"] == "pipeline" and "expected BotB -> BotA with kar" in v["detail"]


def test_abort_is_not_exercised():
    v = ow.judge("[OW] ABORT need two live teammates carrying different primaries\n")
    assert v["status"] == "not_exercised" and "teammates" in v["detail"]


def test_incomplete_window_is_a_pipeline_failure():
    assert ow.judge(BEGIN)["status"] == "pipeline"
