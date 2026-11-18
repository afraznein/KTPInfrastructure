from . import untracked_after_match_scenario as scenario

_PRE = (
    'L 11/18/2026 - 20:00:00: KTP_MATCH_START (matchid "KTP-1") (map "dod_anzio") (half "1st")\n'
    'L 11/18/2026 - 20:05:00: KTP_MATCH_END (matchid "KTP-1") (map "dod_anzio") (status "test")\n'
)
_BEGIN = "L 11/18/2026 - 20:05:01: [KTPAssistDrive.amxx] [AD] PMDMG BEGIN userid=7\n"
_END = "L 11/18/2026 - 20:05:01: [KTPAssistDrive.amxx] [AD] PMDMG END\n"


def _damage(matchid="-", half="0", sequence="0", userid=7, damage=1):
    return (
        f'L 11/18/2026 - 20:05:01: "Bot<{userid}><BOT><Allies>" triggered "damage" '
        f'against "Bot<{userid}><BOT><Allies>" with "garand" (damage "{damage}") '
        f'(damage_capped "{damage}") (hitplace "0") (health_before "100") '
        f'(health_after "100") (damage_applied "0") (matchid "{matchid}") '
        f'(half "{half}") (game_time "312.40") (event_epoch "1794000301") '
        f'(sequence "{sequence}")\n'
    )


class _Handle:
    def __init__(self, path, body):
        self.path = path
        self.body = body

    def rcon(self, command):
        assert command == "ktp_ad_postmatch_damage"
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(self.body)


def _run(tmp_path, monkeypatch, body, pre=_PRE):
    log = tmp_path / "game.log"
    log.write_text(pre, encoding="utf-8")
    monkeypatch.setattr(scenario.time, "sleep", lambda _: None)
    return scenario.run(_Handle(log, body), log)


def test_untracked_damage_after_a_clean_end_passes(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, _BEGIN + _damage() + _END)
    assert result["status"] == "ok", result


def test_gate_left_shut_is_a_pipeline_failure(tmp_path, monkeypatch):
    # What stats_logging 1.39.0 does: the hit reaches the forward and logs nothing.
    result = _run(tmp_path, monkeypatch, _BEGIN + _END)
    assert result["status"] == "pipeline"
    assert "gate stayed shut" in result["detail"]


def test_a_tracked_post_match_line_is_a_pipeline_failure(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch,
                  _BEGIN + _damage(matchid="KTP-1", half="1", sequence="42") + _END)
    assert result["status"] == "pipeline"
    assert "matchid=KTP-1" in result["detail"]


def test_someone_elses_damage_does_not_count(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, _BEGIN + _damage(userid=9) + _END)
    assert result["status"] == "pipeline"
    other_amount = _run(tmp_path, monkeypatch, _BEGIN + _damage(damage=40) + _END)
    assert other_amount["status"] == "pipeline"


def test_damage_before_the_drive_is_not_counted(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, _BEGIN + _END, pre=_PRE + _damage())
    assert result["status"] == "pipeline"


def test_abort_is_not_exercised(tmp_path, monkeypatch):
    body = "L 11/18/2026 - 20:05:01: [KTPAssistDrive.amxx] [AD] PMDMG ABORT need one live player\n"
    assert _run(tmp_path, monkeypatch, body)["status"] == "not_exercised"


def test_a_drive_outside_the_post_end_window_is_not_exercised(tmp_path, monkeypatch):
    no_end = 'L 11/18/2026 - 20:00:00: KTP_MATCH_START (matchid "KTP-1") (map "dod_anzio")\n'
    assert _run(tmp_path, monkeypatch, _BEGIN + _damage() + _END,
                pre=no_end)["status"] == "not_exercised"
    restarted = _PRE + 'L 11/18/2026 - 20:06:00: KTP_MATCH_START (matchid "KTP-2") (map "dod_anzio")\n'
    assert _run(tmp_path, monkeypatch, _BEGIN + _damage() + _END,
                pre=restarted)["status"] == "not_exercised"
    mirror = _PRE + ('L 11/18/2026 - 20:05:00: KTP_MATCH_START (matchid "KTP-1") '
                     '[test-mode mirror]\n')
    assert _run(tmp_path, monkeypatch, _BEGIN + _damage() + _END,
                pre=mirror)["status"] == "ok"


def test_incomplete_window_is_a_pipeline_failure(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, _BEGIN + _damage())["status"] == "pipeline"
