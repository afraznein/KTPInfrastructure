from scripts.lane_b_reliability_report import judge, render


def _report():
    codes = (
        "assist", "cap_break", "suicide", "headshot", "damage_ledger",
        "flag_captures", "flag_positions", "flag_states", "position_samples",
        "capture_buffer_drops", "projectile_killer_not_assister",
        "match_players", "match_frags_tagged", "match_half_set",
        "match_context_cleared", "match_stats_reconciled", "kill_switch",
    )
    return {
        "failures": [],
        "coverage_gaps": ["statsme: bots are skipped"],
        "sql_errors": [],
        "emitted": {"kills": 10, "assist": 2, "cap_break": 1,
                    "damage": 20, "flag_capture": 3, "flag_state": 8,
                    "position_sample": 40},
        "rows": {"match_players": 16},
        "carried": [{"code": code, "status": "ok", "detail": "ok"}
                    for code in codes],
        "break_scenarios": [{"name": "negative_voluntary_walkoff",
                             "status": "ok", "detail": "ok"}],
    }


def test_clean_report_passes_with_statsme_deferred():
    assert judge(_report()) == []


def test_walkoff_gap_blocks_promotion():
    report = _report()
    report["break_scenarios"][0]["status"] = "not_staged"
    assert any("negative_voluntary_walkoff" in problem for problem in judge(report))


def test_five_clean_reports_render_ready(tmp_path):
    reports = [(tmp_path / str(i) / "lane-b-e2e.json", _report())
               for i in range(5)]
    body = render(reports, expected=5)
    assert "Promotion verdict: READY" in body
    assert "every required assertion passed" in body
