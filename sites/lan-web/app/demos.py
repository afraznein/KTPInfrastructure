"""Demo archive queries shared by the demos page and the JSON API."""
from __future__ import annotations

from . import bracket, db
from . import schedule as sched


# Demos that belong to the weekend but not to a tournament match.
GENERIC = {"draft": "Draft night", "scrim": "Scrim", "12man": "12-man"}


def generic_options() -> list[dict]:
    """The non-match choices, in the same {value, label} shape as team_matches."""
    return [{"value": f"gen:{k}", "label": v} for k, v in GENERIC.items()]


def label_maps() -> tuple[dict, dict]:
    """(schedule id -> label, bracket mkey -> label) for a demo's linked match."""
    s_lbl = {m["id"]: f"Sat R{m['round']}: {m['a_name']} v {m['b_name']}" for m in sched.get_matches()}
    b_lbl = {b["mkey"]: bracket.BY_KEY.get(b["mkey"], {}).get("label", b["mkey"]) for b in bracket.get_bracket()}
    return s_lbl, b_lbl


def listing(team: int | None = None) -> list[dict]:
    """Uploaded demos, newest first, each with its team name and match label."""
    where, params = "", []
    if team:
        where, params = "WHERE d.team_id=%s", [team]
    rows = db.query_all(
        "SELECT d.*, t.name AS team_name FROM lan_demos d "
        f"LEFT JOIN lan_teams t ON t.id = d.team_id {where} ORDER BY d.uploaded_at DESC",
        tuple(params),
    )
    s_lbl, b_lbl = label_maps()
    for d in rows:
        d["match_label"] = (s_lbl.get(d["schedule_id"]) if d["schedule_id"]
                            else b_lbl.get(d["bracket_mkey"]) if d["bracket_mkey"]
                            else GENERIC.get(d.get("category")))
    return rows


def team_matches(team_id) -> list[dict]:
    """Matches this team played, as the {value, label} pairs the attach dropdown
    and /api/session both offer. 'sat:<id>' / 'bkt:<mkey>' round-trips to
    demo_routes._parse_match."""
    out = []
    for m in sched.get_matches():
        if team_id in (m["team_a_id"], m["team_b_id"]):
            opp = m["b_name"] if m["team_a_id"] == team_id else m["a_name"]
            out.append({"value": f"sat:{m['id']}", "label": f"Sat R{m['round']} vs {opp}"})
    for b in bracket.get_bracket():
        if team_id in (b["team_a_id"], b["team_b_id"]):
            lbl = bracket.BY_KEY.get(b["mkey"], {}).get("label", b["mkey"])
            opp = b["b_name"] if b["team_a_id"] == team_id else b["a_name"]
            out.append({"value": f"bkt:{b['mkey']}", "label": f"{lbl} vs {opp or 'TBD'}"})
    return out
