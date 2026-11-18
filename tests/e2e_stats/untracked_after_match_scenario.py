"""Drive and judge untracked capture after a clean match end.

`ktp_stats_capture.inc` shuts its untracked gate when a producer context closes.
Until stats_logging 1.39.1 only the next match start reopened it, so a server
logged no untracked damage, frag, assist or cap-break line after its first
match until the process restarted. The fix reopens it at a clean
`ktp_match_end`, and the test-mode end Lane B uses is one: it names the map
being played.

Real damage cannot prove this here. The test-mode end pauses DODX stats, so
bots fighting after it reach no damage forward at all, and a zero would mean
nothing. KTPAssistDrive dispatches one self-inflicted hit through the real
`client_damage` forward instead, which the pause does not gate.
"""

from __future__ import annotations

import re
import time

CODE = "untracked_capture_resumes_after_match_end"

_BEGIN = re.compile(r"\[AD\] PMDMG BEGIN userid=(\d+)")


def judge(log_text: str, begin_offset: int) -> dict:
    """Judge the lines the drive wrote, given where its rcon started reading."""
    lines = log_text.splitlines()
    before, body_lines = lines[:begin_offset], lines[begin_offset:]
    body = "\n".join(body_lines)

    if "[AD] PMDMG ABORT" in body:
        return {"code": CODE, "status": "not_exercised",
                "detail": "KTPAssistDrive found no live player after the match end"}

    match = _BEGIN.search(body)
    if not match or "[AD] PMDMG END" not in body:
        return {"code": CODE, "status": "pipeline",
                "detail": "post-match damage drive did not produce a complete "
                          "BEGIN/END window"}

    ends = [i for i, line in enumerate(before) if "KTP_MATCH_END" in line]
    if not ends or any(
        "KTP_MATCH_START" in line and "[test-mode mirror]" not in line
        for line in before[ends[-1] + 1:]
    ):
        return {"code": CODE, "status": "not_exercised",
                "detail": "the drive did not run between a match end and the "
                          "next match start"}

    userid = match.group(1)
    hit = re.compile(
        rf'"[^"<]*<{userid}><[^>]*><[^>]*>" triggered "damage" against '
        rf'"[^"<]*<{userid}><[^>]*><[^>]*>" with "[^"]*" \(damage "1"\)'
    )
    window = body[match.end():body.index("[AD] PMDMG END")]
    rows = [line for line in window.splitlines() if hit.search(line)]
    if not rows:
        return {"code": CODE, "status": "pipeline",
                "detail": "no damage line for the dispatched post-match hit: the "
                          "untracked gate stayed shut after a clean match end"}
    if len(rows) != 1:
        return {"code": CODE, "status": "pipeline",
                "detail": f"expected one damage line for the dispatched hit; "
                          f"saw {len(rows)}"}

    row = rows[0]
    for field, want in (("matchid", "-"), ("half", "0"), ("sequence", "0")):
        got = re.search(rf'\({field} "([^"]*)"\)', row)
        if not got or got.group(1) != want:
            return {"code": CODE, "status": "pipeline",
                    "detail": f"post-match damage line carried {field}="
                              f"{got.group(1) if got else 'nothing'}, "
                              f"expected the untracked {want!r}"}

    return {"code": CODE, "status": "ok",
            "detail": "a hit after the clean match end logged as untracked "
                      "(matchid -, half 0, sequence 0)"}


def run(handle, log_path) -> dict:
    begin_offset = len(log_path.read_text(errors="replace").splitlines())
    handle.rcon("ktp_ad_postmatch_damage")
    time.sleep(1.0)
    return judge(log_path.read_text(errors="replace"), begin_offset)
