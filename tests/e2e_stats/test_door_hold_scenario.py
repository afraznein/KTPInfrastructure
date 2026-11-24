import hashlib

from . import door_hold_scenario as scenario

_T = "L 11/18/2026 - 20:10:00: "
_DRIVE = _T + "[KTPAssistDrive.amxx] "


def _push(blocked_ms, guard=0):
    return (f"{_T}[KTP_PROFILE] push: blocked=1 rotate=1 move=0 episodes=1 pushers=1 "
            f"untracked=0 client_blocks=1 victims=1 blocked_ms={blocked_ms:.1f} "
            f"guard={guard} guard_skip=0\n")


def _sample(door_yaw=-43.0, bot=(-96.9, -944.0, -76.0), bot_yaw=180.0):
    return (f"{_DRIVE}[DD] SAMPLE door_yaw={door_yaw:.2f} door_avel=100.0 "
            f"bot={bot[0]:.1f} {bot[1]:.1f} {bot[2]:.1f} bot_yaw={bot_yaw:.1f}\n")


def _drive(push_lines, *, bot_yaw=180.0, bot=(-96.9, -944.0, -76.0), door_yaw=-43.0):
    body = (f"{_DRIVE}[DD] BEGIN userid=3 door=180 yaw={bot_yaw:.1f}\n"
            f"{_DRIVE}[DD] OPENED door_yaw=-90.0\n"
            f"{_DRIVE}[DD] PLACED yaw={bot_yaw:.1f}\n")
    for line in push_lines:
        body += _sample(door_yaw, bot, bot_yaw) + line
    return body + _sample(door_yaw, bot, bot_yaw) + f"{_DRIVE}[DD] END\n"


def _judge(body, expect, yaw=180.0, pre="L 11/18/2026 - 20:09:59: earlier\n" + _push(4999.0)):
    # The pre-window push: line is a held interval from an earlier leg; it must not count.
    text = pre + body
    return scenario.judge_leg(text, len(pre.splitlines()), leg="t", yaw=yaw,
                              expect=expect, interval_s=5.0)


def test_a_held_interval_reproduces_the_hold():
    result = _judge(_drive([_push(1200.0), _push(4990.0), _push(5000.0)]), "held")
    assert result["status"] == "ok", result
    assert result["max_blocked_ms"] == 5000.0


def test_no_hold_with_the_guard_off_is_a_failed_reproduction():
    result = _judge(_drive([_push(2.1), _push(0.0)]), "held")
    assert result["status"] == "pipeline"
    assert "reproduction failed" in result["detail"]


def test_a_released_door_passes_the_control():
    result = _judge(_drive([_push(2.1), _push(4.2)], bot_yaw=0.0, door_yaw=-89.0),
                    "released", yaw=0.0)
    assert result["status"] == "ok", result


def test_a_door_still_pressing_fails_the_control():
    result = _judge(_drive([_push(4.2), _push(3100.0)], bot_yaw=0.0), "released", yaw=0.0)
    assert result["status"] == "pipeline"


def test_the_guard_leg_needs_a_counted_retarget():
    ok = _judge(_drive([_push(2.1, guard=1), _push(0.0)]), "guarded")
    assert ok["status"] == "ok", ok
    assert ok["guard"] == 1
    # Released without a re-target: the game reversed it, so the guard was never tested.
    silent = _judge(_drive([_push(2.1), _push(0.0)]), "guarded")
    assert silent["status"] == "pipeline"
    assert "guard= counted nothing" in silent["detail"]
    held = _judge(_drive([_push(5000.0, guard=0)]), "guarded")
    assert held["status"] == "pipeline"


def test_setup_failures_are_not_exercised():
    abort = _judge(f"{_DRIVE}[DD] ABORT door not found at the thunder2 hinge\n", "held")
    assert abort["status"] == "not_exercised"
    assert "door not found" in abort["detail"]

    walked = _judge(_drive([_push(5000.0)], bot=(-200.0, -700.0, -76.0)), "held")
    assert walked["status"] == "not_exercised"
    assert "moved" in walked["detail"]

    turned = _judge(_drive([_push(5000.0)], bot_yaw=150.0), "held", yaw=180.0)
    assert turned["status"] == "not_exercised"
    assert "facing drifted" in turned["detail"]

    no_push = _judge(_drive([]), "held")
    assert no_push["status"] == "not_exercised"
    assert "no push:" in no_push["detail"]


def test_yaw_drift_wraps_around_180():
    # -180 and 180 are the same facing; the drive may log either.
    result = _judge(_drive([_push(5000.0)], bot_yaw=-179.6), "held", yaw=180.0)
    assert result["status"] == "ok", result


def test_an_incomplete_drive_is_a_pipeline_failure():
    body = f"{_DRIVE}[DD] BEGIN userid=3 door=180 yaw=180.0\n{_DRIVE}[DD] OPENED door_yaw=-90.0\n"
    assert _judge(body, "held")["status"] == "pipeline"


def test_summary_takes_the_worst_leg():
    ok = {"leg": "a", "status": "ok", "detail": ""}
    gap = {"leg": "b", "status": "not_exercised", "detail": ""}
    bad = {"leg": "c", "status": "pipeline", "detail": ""}
    assert scenario.summarize([ok, ok])["status"] == "ok"
    assert scenario.summarize([ok, gap])["status"] == "not_exercised"
    assert scenario.summarize([gap, bad, ok])["status"] == "pipeline"
    assert scenario.summarize([ok, gap])["code"] == scenario.CODE


class _Handle:
    """Answers the harness's rcons the way the server would, and writes the drive's log."""

    def __init__(self, log, *, guard=None, refuse=False, legs=(), live_after=1):
        self.log = log
        self.guard = guard
        self.refuse = refuse
        self.legs = list(legs)
        self.sent = []
        # How many ktp_dd_live polls after addbot before the bot is alive; None = never.
        self.live_after = live_after
        self.live_polls = 0

    def rcon(self, command):
        self.sent.append(command)
        name = scenario.GUARD_CVAR
        if command == name:
            if self.guard is None:
                return f'Unknown command "{name}"\n'
            return f'"{name}" is "{self.guard}"\n'
        if command.startswith(name + " "):
            value = command.split()[1]
            self.guard = "0" if self.refuse else value
            return ""
        if command == "ktp_dd_live":
            if "addbot allies" not in self.sent:
                return "[DD] LIVE n=0\n"
            self.live_polls += 1
            alive = self.live_after is not None and self.live_polls >= self.live_after
            return f"[DD] LIVE n={1 if alive else 0}\n"
        if command == "status":
            return "hostname: lane-b\nmap     :  dod_thunder2 at: 0 x, 0 y, 0 z\n"
        if command.startswith("ktp_dd_run"):
            with self.log.open("a", encoding="utf-8") as stream:
                stream.write(self.legs.pop(0))
        return ""

    def wait_ready(self, *, timeout, poll_interval):
        return None


def _serverfiles(tmp_path, content=b"thunder2"):
    maps = tmp_path / "hlds" / "dod" / "maps"
    maps.mkdir(parents=True)
    (maps / "dod_thunder2.bsp").write_bytes(content)
    return tmp_path / "hlds"


def _run(tmp_path, monkeypatch, handle, *, engine_lane=True, content=b"thunder2"):
    monkeypatch.setattr(scenario.time, "sleep", lambda _: None)
    monkeypatch.setattr(scenario, "MAP_MD5", hashlib.md5(b"thunder2").hexdigest())
    serverfiles = _serverfiles(tmp_path, content)
    return scenario.run(handle, handle.log, serverfiles=serverfiles,
                        engine_lane=engine_lane, interval_s=5.0)


def _log(tmp_path):
    log = tmp_path / "game.log"
    log.write_text("L 11/18/2026 - 20:00:00: boot\n", encoding="utf-8")
    return log


_HOLD = _drive([_push(5000.0)])
_RELEASE = _drive([_push(2.1)], bot_yaw=0.0)
_GUARDED = _drive([_push(2.1, guard=1)])


def test_all_three_legs_pass_on_a_guard_engine(tmp_path, monkeypatch):
    handle = _Handle(_log(tmp_path), guard="0", legs=[_HOLD, _RELEASE, _GUARDED])
    result = _run(tmp_path, monkeypatch, handle)
    assert result["status"] == "ok", result
    assert [leg["leg"] for leg in result["legs"]] == ["hold", "release", "guard"]
    assert "changelevel dod_thunder2" in handle.sent
    # The guard is left off for whatever runs after.
    assert handle.sent[-1] == f"{scenario.GUARD_CVAR} 0"


def test_an_engine_without_the_cvar_still_reproduces_but_cannot_prove(tmp_path, monkeypatch):
    handle = _Handle(_log(tmp_path), guard=None, legs=[_HOLD, _RELEASE])
    result = _run(tmp_path, monkeypatch, handle)
    assert result["status"] == "not_exercised"
    assert result["legs"][0]["status"] == "ok"
    assert "has no ktp_door_reversal_guard" in result["legs"][2]["detail"]
    assert not any(c.startswith(scenario.GUARD_CVAR + " ") for c in handle.sent)


def test_a_refused_guard_is_not_exercised(tmp_path, monkeypatch):
    handle = _Handle(_log(tmp_path), guard="0", refuse=True, legs=[_HOLD, _RELEASE])
    result = _run(tmp_path, monkeypatch, handle)
    assert result["status"] == "not_exercised"
    assert "not the build" in result["legs"][2]["detail"]


def test_missing_preconditions_never_touch_the_server(tmp_path, monkeypatch):
    handle = _Handle(_log(tmp_path), guard="0")
    result = _run(tmp_path, monkeypatch, handle, engine_lane=False)
    assert result["status"] == "not_exercised"
    assert "engine lane" in result["detail"]
    assert handle.sent == []


def test_a_missing_or_different_map_is_not_exercised(tmp_path, monkeypatch):
    monkeypatch.setattr(scenario.time, "sleep", lambda _: None)
    handle = _Handle(_log(tmp_path), guard="0")
    result = scenario.run(handle, handle.log, serverfiles=tmp_path / "empty",
                          engine_lane=True, interval_s=5.0)
    assert result["status"] == "not_exercised"
    assert "not in the Lane B image" in result["detail"]

    other = _run(tmp_path, monkeypatch, handle, content=b"another build")
    assert other["status"] == "not_exercised"
    assert "measured on" in other["detail"]
    assert handle.sent == []


def test_the_bot_is_added_after_the_changelevel_and_before_the_drive(tmp_path, monkeypatch):
    handle = _Handle(_log(tmp_path), guard="0", legs=[_HOLD, _RELEASE, _GUARDED], live_after=3)
    result = _run(tmp_path, monkeypatch, handle)
    assert result["status"] == "ok", result
    sent = handle.sent
    change = sent.index("changelevel dod_thunder2")
    add = sent.index("addbot allies")
    first_drive = next(i for i, c in enumerate(sent) if c.startswith("ktp_dd_run"))
    assert change < sent.index("balance teams off") < add < first_drive
    assert sent.count("addbot allies") == 1
    assert handle.live_polls == 3


def test_a_bot_that_never_spawns_is_not_exercised_and_the_drive_never_runs(tmp_path, monkeypatch):
    handle = _Handle(_log(tmp_path), guard="0", live_after=None)
    result = _run(tmp_path, monkeypatch, handle)
    assert result["status"] == "not_exercised"
    assert "no live player" in result["detail"]
    assert not any(c.startswith("ktp_dd_run") for c in handle.sent)
    assert handle.live_polls == scenario.BOT_SPAWN_POLLS


def test_the_drive_registers_the_live_probe_the_scenario_polls():
    from pathlib import Path
    sma = (Path(scenario.__file__).parent / "diagnostics/KTPAssistDrive.sma").read_text(encoding="utf-8")
    assert 'register_srvcmd("ktp_dd_live", "cmd_door_live")' in sma
    assert 'server_print("[DD] LIVE n=%d", num)' in sma
