from . import assist_scenario


class _Handle:
    def __init__(self, path, body):
        self.path = path
        self.body = body

    def rcon(self, command):
        assert command == "ktp_ad_run"
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(self.body)


def _run(tmp_path, monkeypatch, assists):
    log = tmp_path / "game.log"
    log.write_text("warmup\n", encoding="utf-8")
    body = (
        "L 08/14/2026 - 20:00:00: [KTPAssistDrive.amxx] "
        "[AD] BEGIN victim=3 vname=Victim killer=4 kname=Killer "
        "assister=6 aname=Helper\n"
        + assists
        + "L 08/14/2026 - 20:00:00: [KTPAssistDrive.amxx] [AD] END\n"
    )
    monkeypatch.setattr(assist_scenario.time, "sleep", lambda _: None)
    return assist_scenario.run(_Handle(log, body), log)


def test_degraded_killer_scenario_accepts_only_third_party(tmp_path, monkeypatch):
    result = _run(
        tmp_path, monkeypatch,
        'L 08/14/2026 - 20:00:00: "Helper<6><BOT><Axis>" triggered "assist" '
        'against "Victim<3><BOT><Allies>"\n')
    assert result["status"] == "ok"


def test_degraded_killer_scenario_rejects_killer_assist(tmp_path, monkeypatch):
    result = _run(
        tmp_path, monkeypatch,
        'L 08/14/2026 - 20:00:00: "Helper<6><BOT><Axis>" triggered "assist" '
        'against "Victim<3><BOT><Allies>"\n'
        'L 08/14/2026 - 20:00:00: "Killer<4><BOT><Axis>" triggered "assist" '
        'against "Victim<3><BOT><Allies>"\n')
    assert result["status"] == "pipeline"
    assert "credited killer" in result["detail"]
