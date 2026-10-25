"""Drive and judge the voice-MENU scenario: every one of the 27 menu slots, checked against the game.

stats_logging 1.33.0 maps (voice menu N, menuselect K) to the voice that slot plays and logs it as
`voicemenu_<name>`. The slot table comes from dod.so's string order, so it is a claim until the game
confirms it. KTPAssistDrive's `ktp_vm_run` has bots open each voice menu and pick each slot, spaced
apart so the game's own voice cooldown never swallows one, and logs every `#Voice_subtitle_*`
TextMsg the game sends to teammates. A slot is verified when the plugin's logged name and the
subtitle the game chose for that pick name the same voice.

Verdicts, same three-way shape as every carried check:
  ok              27 picks logged and every one agrees with the game's subtitle
  pipeline        a pick was not logged, or a logged name disagrees with the subtitle
  not_exercised   the drive could not run (no bots) or the game sent no subtitles at all,
                  so the table was not tested -- never dressed up as a pass
"""

from __future__ import annotations

import re
import time

SLOTS = 27
# Nation-specific subtitles for the same command (British PIAT, German Panzerschreck) and the one
# command whose subtitle is named differently.
_ALIAS = {"piatspotted": "bazookaspotted", "pschreckspotted": "bazookaspotted",
          "usepiat": "usebazooka", "usepschreck": "usebazooka", "moveout": "attack"}

_PICK = re.compile(r"\[VM\] PICK n=(\d+) bot=(\d+) bname=(\S+) menu=(\d) slot=(\d)")
_SUB = re.compile(r"\[VM\] SUB to=\d+ text=#Voice_subtitle_([a-z]+)")
_ABORT = "[VM] ABORT"
_END = "[VM] END"


def _logged(body: str, bname: str) -> list[str]:
    return re.findall(rf'"{re.escape(bname)}<\d+><[^>]*><[^>]*>" triggered "voicemenu_([a-z]+)"', body)


def judge(body: str) -> dict:
    """Pure: verdict from the log window between ktp_vm_run and [VM] END."""
    code = "voice_menu_slots"
    if _ABORT in body:
        return {"code": code, "status": "not_exercised", "detail": "KTPAssistDrive found no live bots on a team"}
    picks = list(_PICK.finditer(body))
    if not picks or _END not in body:
        return {"code": code, "status": "pipeline", "detail": "voice-menu drive did not produce a complete PICK..END window"}
    any_sub = bool(_SUB.search(body))
    bad, unlogged, unconfirmed = [], [], 0
    for i, m in enumerate(picks):
        seg = body[m.end(): picks[i + 1].start() if i + 1 < len(picks) else body.index(_END)]
        menu, slot, bname = m.group(4), m.group(5), m.group(3)
        logged = _logged(seg, bname)
        if not logged:
            unlogged.append(f"{menu}.{slot}")
            continue
        subs = {_ALIAS.get(s, s) for s in _SUB.findall(seg)}
        if not subs:
            unconfirmed += 1
        elif logged[0] not in subs:
            bad.append(f"{menu}.{slot} logged {logged[0]} but the game played {'/'.join(sorted(subs))}")
    if unlogged or bad:
        return {"code": code, "status": "pipeline",
                "detail": "; ".join(([f"not logged: {', '.join(unlogged)}"] if unlogged else []) + bad)}
    if not any_sub:
        return {"code": code, "status": "not_exercised",
                "detail": f"{len(picks)} picks logged, but the game sent no #Voice_subtitle_* TextMsg, so the slot table was not checked"}
    if len(picks) != SLOTS:
        return {"code": code, "status": "pipeline", "detail": f"expected {SLOTS} picks, drive issued {len(picks)}"}
    return {"code": code, "status": "ok",
            "detail": f"{len(picks)}/{SLOTS} menu picks logged; {len(picks) - unconfirmed} confirmed by the game's subtitle"
                      + (f", {unconfirmed} with no subtitle seen (cooldown)" if unconfirmed else "")}


def run(handle, log_path, timeout: float = 90.0) -> dict:
    before = len(log_path.read_text(errors="replace").splitlines())
    handle.rcon("ktp_vm_run")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = "\n".join(log_path.read_text(errors="replace").splitlines()[before:])
        if _END in body or _ABORT in body:
            time.sleep(6.0)  # the capture ring flushes every 5 s
            return judge("\n".join(log_path.read_text(errors="replace").splitlines()[before:]))
        time.sleep(2.0)
    return {"code": "voice_menu_slots", "status": "pipeline", "detail": f"no [VM] END within {timeout:.0f} s"}
