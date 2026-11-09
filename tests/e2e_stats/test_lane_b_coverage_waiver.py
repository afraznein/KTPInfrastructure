"""The all-bot coverage waiver: which not_exercised verdicts may fail the run.

Ruled 2026-11-03 for `voice_menu_slots`. Everything here is asked of the
behaviour; the previous guard on this wiring asserted a source line and went
stale the moment the gating set stopped being every gap.
"""

import ast
from pathlib import Path

from scripts.lane_b_e2e import (UNEXERCISABLE_IN_ALL_BOT_LANE,
                                gating_coverage_gaps, run_exit_code)
from tests.e2e_stats.table_report import render_markdown
from tests.source_anchors import sole_call_site


VOICE_DETAIL = ("27 picks logged, but the game sent no #Voice_subtitle_* "
                "TextMsg, so the slot table was not checked")


def _report(*carried, extra=()):
    gaps = [f"{c['code']}: {c['detail']}" for c in carried
            if c["status"] == "not_exercised"]
    return {"carried": list(carried), "coverage_gaps": gaps + list(extra)}


def _voice(status="not_exercised", detail=VOICE_DETAIL):
    return {"code": "voice_menu_slots", "status": status, "detail": detail}


def _cap_break(status="not_exercised"):
    return {"code": "cap_break", "status": status,
            "detail": "no cap_break this run"}


def test_the_waived_gap_is_reported_and_does_not_gate():
    report = _report(_voice())
    assert report["coverage_gaps"], "the gap must still be reported"
    assert gating_coverage_gaps(report) == []
    assert run_exit_code(failures=[], gating_gaps=gating_coverage_gaps(report),
                         require_complete_coverage=True) == 0


def test_an_ordinary_gap_still_gates():
    report = _report(_cap_break())
    assert gating_coverage_gaps(report) == ["cap_break: no cap_break this run"]
    assert run_exit_code(failures=[], gating_gaps=gating_coverage_gaps(report),
                         require_complete_coverage=True) == 1


def test_a_waived_code_beside_a_real_gap_does_not_rescue_the_run():
    report = _report(_voice(), _cap_break())
    assert len(report["coverage_gaps"]) == 2
    assert gating_coverage_gaps(report) == ["cap_break: no cap_break this run"]
    assert run_exit_code(failures=[], gating_gaps=gating_coverage_gaps(report),
                         require_complete_coverage=True) == 1


def test_the_waiver_covers_only_not_exercised_never_a_defect():
    """A wrong slot is a `pipeline` verdict and reaches `failures`, not `gaps`.

    This is the direction that would make the waiver dangerous: it must not be
    reachable by a check that found something.
    """
    report = _report(_voice(status="pipeline",
                            detail="1.3 logged usebazooka but the game played attack"))
    assert report["coverage_gaps"] == []
    assert run_exit_code(failures=["voice_menu_slots: 1.3 logged ..."],
                         gating_gaps=[], require_complete_coverage=True) == 1


def test_a_gap_that_no_carried_check_produced_still_gates():
    report = _report(_voice(), extra=["2 known all-bot SQL artifact(s):\n  ..."])
    assert gating_coverage_gaps(report) == [
        "2 known all-bot SQL artifact(s):\n  ..."]


def test_a_formatting_change_re_arms_the_gate_rather_than_widening_it():
    """Mutation: if the gap text stops matching what `carried` renders, the run
    must go back to failing. A silent widening is the unsafe direction."""
    report = _report(_voice())
    report["coverage_gaps"] = ["voice_menu_slots -- " + VOICE_DETAIL]
    assert gating_coverage_gaps(report) == report["coverage_gaps"]
    assert run_exit_code(failures=[], gating_gaps=gating_coverage_gaps(report),
                         require_complete_coverage=True) == 1


def test_a_report_with_no_carried_list_gates_on_every_gap():
    report = {"coverage_gaps": ["voice_menu_slots: " + VOICE_DETAIL]}
    assert gating_coverage_gaps(report) == report["coverage_gaps"]


def test_dropping_the_waiver_set_makes_the_waived_gap_gate_again():
    """Control on the test itself: the pass above is not true by construction."""
    assert "voice_menu_slots" in UNEXERCISABLE_IN_ALL_BOT_LANE
    report = _report(_voice(detail="a code nothing waives"))
    report["carried"][0]["code"] = "cap_break"
    report["coverage_gaps"] = ["cap_break: a code nothing waives"]
    assert gating_coverage_gaps(report) == report["coverage_gaps"]


def test_the_summary_marks_a_waived_gap_and_leaves_the_others_plain():
    report = _report(_voice(), _cap_break())
    report["coverage_gaps_gating"] = gating_coverage_gaps(report)
    lines = [line for line in render_markdown(report).splitlines()
             if line.startswith("- ")]
    waived = [line for line in lines if "waived" in line]
    assert len(waived) == 1 and "voice_menu_slots" in waived[0]
    assert any(line.startswith("- cap_break") and "waived" not in line
               for line in lines)


def test_the_summary_marks_nothing_when_no_gating_set_was_recorded():
    report = _report(_voice())
    assert "waived" not in render_markdown(report)


def test_the_runner_feeds_the_gating_set_to_the_exit_code():
    """Asked of the parse tree: a sentence about a call cannot answer for it."""
    source = (Path(__file__).resolve().parents[2]
              / "scripts/lane_b_e2e.py").read_text(encoding="utf-8")
    gating_at, _ = sole_call_site(source, "gating_coverage_gaps", "lane_b_e2e.py")
    exit_at, _ = sole_call_site(source, "run_exit_code", "lane_b_e2e.py")
    assert gating_at < exit_at

    call = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "run_exit_code")
    passed = {kw.arg: kw.value for kw in call.keywords}
    assert isinstance(passed["gating_gaps"], ast.Name)
    assert passed["gating_gaps"].id == "gating_gaps"
