"""Drive and judge a long rotating-door hold, with and without the engine's reversal guard.

A closing `func_door_rotating` that is blocked by a player asks the game which way to
reopen. DoD's `DoorGoUp` picks the side from the facing of whoever opened the door, and for
about half of all facings that side lies past the blocker, so the door keeps pressing into
him for as long as nobody moves: seconds of `blocked_ms` in the engine's `push:` record. The
reproduction and the model behind it are KTP-ReHLDS `design/rotating-door-holds/`; the fix is
KTP-ReHLDS `ktp_door_reversal_guard` (default 0).

The scenario is the modelled one: `dod_thunder2`, the door hinged at (-152 -920 -66) (BSP
entity 241), one bot that opens it from the north and is then stood south of it, inside the
leaf's closing arc. The bot is the door's activator, so its facing is the one the game reads.
Three legs, each judged on `push:` `blocked_ms` between the drive's markers:

  hold     guard 0, facing 180  the door must hold (most of every interval blocked)
  release  guard 0, facing 0    control: the first reversal works, a few ms at most
  guard    guard 1, facing 180  the guard turns it back: a few ms, and guard= counts it

The changelevel drops every bot (the engine drops fake clients on a level change), so the
scenario adds its one bot itself, with new_bot's `addbot`, and waits for it to be alive.

Everything this cannot set up is `not_exercised`, never a failure: the map missing from the
image or a different build of it, a lane without engine telemetry, an engine without the
cvar or one that refused it, no bot alive after `addbot`, the drive aborting, or the bot
moving or turning on its own. A
`pipeline` result means the drive ran as designed and the door did the wrong thing.

The scenario changes the map, so the harness runs it last and only when asked
(`--door-scenario`).
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

CODE = "door_hold_reversal_guard"
MAP = "dod_thunder2"
# Door 241's geometry and the bot positions were measured on this build of the map.
MAP_MD5 = "68d6c078e63d7c32e75cc3de1ca5793f"
GUARD_CVAR = "ktp_door_reversal_guard"

HOLD_YAW = 180.0
RELEASE_YAW = 0.0
# A held interval is mostly blocked; the design note's fleet holds read 9.4 s of 10.
HOLD_SHARE = 0.8
# One clean reversal costs one or two pusher steps, about 2 ms each.
RELEASE_MS = 10.0
# The leaf carries the bot about 24 units into the corner before it stops.
MAX_DRIFT = 48.0
MAX_YAW_DRIFT = 1.0

CHANGELEVEL_SETTLE = 5.0
SPAWN_SETTLE = 15.0
# new_bot joins a team and picks a class before it spawns; polled once a second.
BOT_SPAWN_POLLS = 45
BOT_TEAM = "allies"
# The drive opens the door, waits 1.5 s, then samples for 16 s.
LEG_SECONDS = 20.0
# Time for the released door to finish its cycle and close before the next leg.
RESET_SECONDS = 10.0

_KV = re.compile(r"(\w+)=(-?[0-9.]+)")
_LIVE = re.compile(r"\[DD\] LIVE n=(\d+)")
_PLACED_AT = (-111.0, -964.0, -76.0)


def _status(statuses: list[str]) -> str:
    if "pipeline" in statuses:
        return "pipeline"
    if "not_exercised" in statuses:
        return "not_exercised"
    return "ok"


def _yaw_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _leg(name: str, status: str, detail: str, **extra) -> dict:
    return {"leg": name, "status": status, "detail": detail, **extra}


def judge_leg(log_text: str, begin_offset: int, *, leg: str, yaw: float,
              expect: str, interval_s: float) -> dict:
    """Judge one drive run from the lines written after `begin_offset`.

    `expect` is "held" for the guard-off hold, "released" for the control, and
    "guarded" for the guard-on run, which must also count a re-target.
    """
    lines = log_text.splitlines()[begin_offset:]
    for line in lines:
        if "[DD] ABORT" in line:
            return _leg(leg, "not_exercised",
                        "the drive aborted: " + line.split("[DD] ABORT", 1)[1].strip())

    def index(marker: str) -> int:
        for i, line in enumerate(lines):
            if marker in line:
                return i
        return -1

    placed, end = index("[DD] PLACED"), index("[DD] END")
    if index("[DD] BEGIN") < 0 or index("[DD] OPENED") < 0 or placed < 0 or end < placed:
        return _leg(leg, "pipeline", "the door drive did not complete BEGIN/OPENED/PLACED/END")

    window = lines[placed + 1:end]
    samples = []
    for line in window:
        if "[DD] SAMPLE" not in line:
            continue
        kv = dict(_KV.findall(line))
        bot = re.search(r"bot=(-?[0-9.]+) (-?[0-9.]+) (-?[0-9.]+)", line)
        if not bot or "bot_yaw" not in kv or "door_yaw" not in kv:
            continue
        samples.append({"door_yaw": float(kv["door_yaw"]),
                        "bot": tuple(float(v) for v in bot.groups()),
                        "bot_yaw": float(kv["bot_yaw"])})
    if not samples:
        return _leg(leg, "pipeline", "the drive logged no SAMPLE lines")

    drift = max(sum((s["bot"][i] - _PLACED_AT[i]) ** 2 for i in range(3)) ** 0.5
                for s in samples)
    if drift > MAX_DRIFT:
        return _leg(leg, "not_exercised",
                    f"the bot moved {drift:.0f} units from where it was stood "
                    f"(limit {MAX_DRIFT:.0f}); its AI walked it off the spot")
    turned = max(_yaw_diff(s["bot_yaw"], yaw) for s in samples)
    if turned > MAX_YAW_DRIFT:
        return _leg(leg, "not_exercised",
                    f"the bot's facing drifted {turned:.1f} degrees from {yaw:g}")

    push = [dict(_KV.findall(line)) for line in window if "[KTP_PROFILE] push:" in line]
    push = [p for p in push if "blocked_ms" in p]
    if not push:
        return _leg(leg, "not_exercised",
                    "no push: record with blocked_ms between PLACED and END "
                    "(ktp_profile_frame off, or an engine older than blocked_ms)")

    worst = max(float(p["blocked_ms"]) for p in push)
    guards = sum(int(float(p.get("guard", 0))) for p in push)
    door = (min(s["door_yaw"] for s in samples), max(s["door_yaw"] for s in samples))
    evidence = {"max_blocked_ms": worst, "guard": guards, "push_records": len(push),
                "door_yaw_range": door, "samples": len(samples)}
    held_ms = HOLD_SHARE * interval_s * 1000.0
    seen = (f"worst interval {worst:.1f} ms blocked over {len(push)} push: record(s), "
            f"door yaw {door[0]:.1f}..{door[1]:.1f}, guard={guards}")

    if expect == "held":
        if worst >= held_ms:
            return _leg(leg, "ok", f"facing {yaw:g} held the door: {seen}", **evidence)
        return _leg(leg, "pipeline",
                    f"facing {yaw:g} with the guard off did not hold the door (needed "
                    f">= {held_ms:.0f} ms): {seen}. The reproduction failed, so the "
                    "guard leg proves nothing", **evidence)
    if worst > RELEASE_MS:
        return _leg(leg, "pipeline",
                    f"facing {yaw:g} left the door pressing into the bot (allowed "
                    f"<= {RELEASE_MS:.0f} ms): {seen}", **evidence)
    if expect == "guarded" and guards < 1:
        return _leg(leg, "pipeline",
                    f"the door released but guard= counted nothing, so the game reversed "
                    f"it by itself and the guard was not what this measured: {seen}",
                    **evidence)
    return _leg(leg, "ok", f"facing {yaw:g} released the door: {seen}", **evidence)


def summarize(legs: list[dict]) -> dict:
    status = _status([leg["status"] for leg in legs])
    detail = "; ".join(f"{leg['leg']}: {leg['status']} ({leg['detail']})" for leg in legs)
    return {"code": CODE, "status": status, "detail": detail, "legs": legs}


def _not_exercised(detail: str) -> dict:
    return {"code": CODE, "status": "not_exercised", "detail": detail, "legs": []}


def _run_leg(handle, log_path: Path, *, leg: str, yaw: float, expect: str,
             interval_s: float) -> dict:
    begin = len(log_path.read_text(errors="replace").splitlines())
    handle.rcon(f"ktp_dd_run {yaw:g}")
    time.sleep(LEG_SECONDS)
    result = judge_leg(log_path.read_text(errors="replace"), begin, leg=leg, yaw=yaw,
                       expect=expect, interval_s=interval_s)
    time.sleep(RESET_SECONDS)
    return result


def _guard_value(handle) -> str | None:
    reply = handle.rcon(GUARD_CVAR) or ""
    found = re.search(rf'"{GUARD_CVAR}" is "([^"]*)"', reply)
    return found.group(1) if found else None


def _live_players(handle) -> int:
    found = _LIVE.search(handle.rcon("ktp_dd_live") or "")
    return int(found.group(1)) if found else 0


def _add_bot(handle) -> int:
    """Add the drive's bot and wait for it to spawn. Returns the live count seen last."""
    # Teams of one and zero are uneven; balancing must not kick the only bot.
    handle.rcon("balance teams off")
    handle.rcon(f"addbot {BOT_TEAM}")
    live = 0
    for _ in range(BOT_SPAWN_POLLS):
        live = _live_players(handle)
        if live:
            return live
        time.sleep(1.0)
    return live


def run(handle, log_path: Path, *, serverfiles: Path, engine_lane: bool,
        interval_s: float) -> dict:
    if not engine_lane:
        return _not_exercised("push: blocked_ms is logged only in the engine lane; "
                              "dispatch with engine_ref")
    bsp = Path(serverfiles) / "dod" / "maps" / f"{MAP}.bsp"
    if not bsp.is_file():
        return _not_exercised(f"{MAP}.bsp is not in the Lane B image")
    digest = hashlib.md5(bsp.read_bytes()).hexdigest()
    if digest != MAP_MD5:
        return _not_exercised(f"{MAP}.bsp is md5 {digest}, not the {MAP_MD5} build "
                              "door 241 was measured on")

    has_guard = _guard_value(handle) is not None
    if has_guard:
        handle.rcon(f"{GUARD_CVAR} 0")

    handle.rcon(f"changelevel {MAP}")
    time.sleep(CHANGELEVEL_SETTLE)
    handle.wait_ready(timeout=60.0, poll_interval=1.0)
    if MAP not in (handle.rcon("status") or ""):
        return _not_exercised(f"changelevel {MAP} did not take")
    time.sleep(SPAWN_SETTLE)
    if not _add_bot(handle):
        return _not_exercised(f"no live player {BOT_SPAWN_POLLS} s after `addbot {BOT_TEAM}` "
                              f"on {MAP}; new_bot ships no waypoints for it, which may be why")

    legs = [
        _run_leg(handle, log_path, leg="hold", yaw=HOLD_YAW, expect="held",
                 interval_s=interval_s),
        _run_leg(handle, log_path, leg="release", yaw=RELEASE_YAW, expect="released",
                 interval_s=interval_s),
    ]
    if not has_guard:
        legs.append(_leg("guard", "not_exercised", f"this engine has no {GUARD_CVAR}"))
    else:
        handle.rcon(f"{GUARD_CVAR} 1")
        # The engine checks the game DLL on the next pusher frame and disarms on a mismatch.
        time.sleep(1.0)
        if _guard_value(handle) != "1":
            legs.append(_leg("guard", "not_exercised",
                             f"the engine set {GUARD_CVAR} back to 0: the game DLL is not "
                             "the build the guard was written for"))
        else:
            legs.append(_run_leg(handle, log_path, leg="guard", yaw=HOLD_YAW,
                                 expect="guarded", interval_s=interval_s))
        handle.rcon(f"{GUARD_CVAR} 0")
    return summarize(legs)
