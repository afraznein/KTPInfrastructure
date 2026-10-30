"""Drive and judge the own-weapon kill scenario (stats_logging 1.34.0, KTPHLStatsX migration 051).

stats_logging keeps an owner stamp on every carried primary: DODX's `dod_client_weaponpickup` is
silent at spawn and death, so a death or the drop key puts the gun on a ground list and a pickup
claims the nearest gun of that type. A kill with a gun whose first owner is the victim logs
`"<killer>" triggered "own_weapon_kill" against "<victim>" with "<weapon>"`.

KTPAssistDrive's `ktp_ow_run` kills teammate A for real, has teammate B press the drop key and puts B
on A's body, logs every `dod_client_weaponpickup` the game fires for B as `[OW] FWD`, and then
dispatches a teamkill of A by B with A's gun. If the game hands B nothing in 5 s it calls the plugin's
handler directly (`[OW] SYNTHETIC`), which still tests the ledger but not the game's pickup.

Verdicts:
  ok              the game's own pickup reached the forward and exactly one own_weapon_kill names B, A
                  and A's gun
  pipeline        no line, more than one, or a line naming the wrong players or gun
  not_exercised   no suitable teammates, or the pickup was synthetic: the ledger is tested, the game's
                  pickup is not -- never dressed up as a pass
"""

from __future__ import annotations

import re
import time

CODE = "own_weapon_kill_scenario"
_BEGIN = re.compile(r"\[OW\] BEGIN a=\d+ aname=(\S+) b=\d+ bname=(\S+) wpn=(\S+)")
_END = re.compile(r"\[OW\] END mode=(real|synthetic)")
_ABORT = "[OW] ABORT"
_LINE = re.compile(r'"([^"<]*)<\d+><[^>]*><[^>]*>" triggered "own_weapon_kill" against '
                   r'"([^"<]*)<\d+><[^>]*><[^>]*>" with "([^"]+)"')


def judge(body: str) -> dict:
    """Pure: verdict from the log window between ktp_ow_run and [OW] END."""
    if _ABORT in body:
        return {"code": CODE, "status": "not_exercised", "detail": body.split(_ABORT, 1)[1].splitlines()[0].strip()}
    begin, end = _BEGIN.search(body), _END.search(body)
    if not begin or not end:
        return {"code": CODE, "status": "pipeline", "detail": "own-weapon drive did not produce a complete BEGIN..END window"}
    aname, bname, wpn = begin.groups()
    lines = _LINE.findall(body)
    if len(lines) != 1:
        return {"code": CODE, "status": "pipeline", "detail": f"expected one own_weapon_kill line, saw {len(lines)}"}
    if lines[0] != (bname, aname, wpn):
        return {"code": CODE, "status": "pipeline",
                "detail": f"own_weapon_kill names {lines[0][0]} -> {lines[0][1]} with {lines[0][2]}, "
                          f"expected {bname} -> {aname} with {wpn}"}
    fwd = len(re.findall(r"\[OW\] FWD id=\d+ wpn=\d+ value=1", body))
    if end.group(1) == "synthetic":
        return {"code": CODE, "status": "not_exercised",
                "detail": f"ledger ok ({bname} -> {aname} with {wpn}); the game handed {bname} no gun in 5 s, "
                          f"so the pickup was synthetic ({fwd} real pickup forwards)"}
    return {"code": CODE, "status": "ok",
            "detail": f"game pickup reached dod_client_weaponpickup; {bname} -> {aname} with {wpn} logged once"}


def run(handle, log_path, timeout: float = 30.0) -> dict:
    before = len(log_path.read_text(errors="replace").splitlines())
    handle.rcon("ktp_ow_run")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = "\n".join(log_path.read_text(errors="replace").splitlines()[before:])
        if _END.search(body) or _ABORT in body:
            time.sleep(6.0)  # the capture ring flushes every 5 s
            return judge("\n".join(log_path.read_text(errors="replace").splitlines()[before:]))
        time.sleep(1.0)
    return {"code": CODE, "status": "pipeline", "detail": f"no [OW] END within {timeout:.0f} s"}
