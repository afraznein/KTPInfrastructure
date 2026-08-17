"""Drive and judge KTPAssistDrive's degraded-killer scenario."""

from __future__ import annotations

import re
import time


_BEGIN = re.compile(
    r"\[AD\] BEGIN victim=(\d+) vname=(\S+) killer=(\d+) kname=(\S+) "
    r"assister=(\d+) aname=(\S+)"
)


def run(handle, log_path) -> dict:
    before = len(log_path.read_text(errors="replace").splitlines())
    handle.rcon("ktp_ad_run")
    time.sleep(1.0)
    lines = log_path.read_text(errors="replace").splitlines()[before:]
    body = "\n".join(lines)

    if "[AD] ABORT" in body:
        return {"code": "projectile_killer_not_assister", "status": "not_exercised",
                "detail": "KTPAssistDrive could not find one victim and two live enemies"}

    match = _BEGIN.search(body)
    if not match or "[AD] END" not in body:
        return {"code": "projectile_killer_not_assister", "status": "pipeline",
                "detail": "assist diagnostic did not produce a complete BEGIN/END window"}

    victim_id, victim_name, killer_id, killer_name, assister_id, assister_name = match.groups()
    expected = re.compile(
        rf'"{re.escape(assister_name)}<{assister_id}><[^>]*><[^>]*>" '
        rf'triggered "assist" against "{re.escape(victim_name)}<{victim_id}>'
    )
    forbidden = re.compile(
        rf'"{re.escape(killer_name)}<{killer_id}><[^>]*><[^>]*>" '
        rf'triggered "assist" against "{re.escape(victim_name)}<{victim_id}>'
    )
    expected_count = len(expected.findall(body))
    forbidden_count = len(forbidden.findall(body))
    if forbidden_count:
        return {"code": "projectile_killer_not_assister", "status": "pipeline",
                "detail": f"degraded death callback credited killer {killer_name} "
                          f"with {forbidden_count} assist(s) against {victim_name}"}
    if expected_count != 1:
        return {"code": "projectile_killer_not_assister", "status": "pipeline",
                "detail": f"expected exactly one assist from {assister_name} against "
                          f"{victim_name}; saw {expected_count}"}
    return {"code": "projectile_killer_not_assister", "status": "ok",
            "detail": f"third party {assister_name} credited once; final attacker "
                      f"{killer_name} excluded with degraded callback killer"}
