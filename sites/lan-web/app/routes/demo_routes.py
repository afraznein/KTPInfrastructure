"""Demo / VOD archive. Uploads are zipped server-side (DoD .dem compresses hard)
and require the uploader's alias. Download serves the stored zip."""
import re
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from .. import auth, bracket, common, db
from .. import schedule as sched
from ..config import settings
from ..templating import templates

router = APIRouter()
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _parse_match(raw: str):
    """'sat:123' / 'bkt:QF1' -> (schedule_id, bracket_mkey)."""
    raw = (raw or "").strip()
    if raw.startswith("sat:") and raw[4:].isdigit():
        return int(raw[4:]), None
    if raw.startswith("bkt:") and raw[4:]:
        return None, raw[4:][:8]
    return None, None


@router.get("/demos", name="demos")
def demos_page(request: Request, team: int | None = None):
    where, params = "", []
    if team:
        where, params = "WHERE d.team_id=%s", [team]
    rows = db.query_all(
        "SELECT d.*, t.name AS team_name FROM lan_demos d "
        f"LEFT JOIN lan_teams t ON t.id = d.team_id {where} ORDER BY d.uploaded_at DESC",
        tuple(params),
    )
    # resolve each demo's linked match label
    s_lbl = {m["id"]: f"Sat R{m['round']}: {m['a_name']} v {m['b_name']}" for m in sched.get_matches()}
    b_lbl = {b["mkey"]: bracket.BY_KEY.get(b["mkey"], {}).get("label", b["mkey"]) for b in bracket.get_bracket()}
    for d in rows:
        d["match_label"] = (s_lbl.get(d["schedule_id"]) if d["schedule_id"]
                            else b_lbl.get(d["bracket_mkey"]) if d["bracket_mkey"] else None)
    # matches the uploader's own team played — the attach dropdown
    my_matches, ident = [], auth.current_identity(request)
    if ident:
        tid = ident["team_id"]
        for m in sched.get_matches():
            if tid in (m["team_a_id"], m["team_b_id"]):
                opp = m["b_name"] if m["team_a_id"] == tid else m["a_name"]
                my_matches.append({"value": f"sat:{m['id']}", "label": f"Sat R{m['round']} vs {opp}"})
        for b in bracket.get_bracket():
            if tid in (b["team_a_id"], b["team_b_id"]):
                lbl = bracket.BY_KEY.get(b["mkey"], {}).get("label", b["mkey"])
                opp = b["b_name"] if b["team_a_id"] == tid else b["a_name"]
                my_matches.append({"value": f"bkt:{b['mkey']}", "label": f"{lbl} vs {opp or 'TBD'}"})
    ctx = common.base_ctx(request, "demos")
    ctx["demos"] = rows
    ctx["max_mb"] = settings.demo_max_bytes // (1024 * 1024)
    ctx["teams"] = db.query_all("SELECT id, name FROM lan_teams ORDER BY name")
    ctx["filter_team"] = team
    ctx["my_matches"] = my_matches
    ctx["is_admin"] = auth.is_admin(request)
    return templates.TemplateResponse(request, "demos.html", ctx)


@router.post("/demos/upload", name="demo_upload")
async def demos_upload(
    request: Request,
    file: UploadFile = File(...),
    note: str = Form(""),
    match: str = Form(""),
):
    # Upload requires a roster-linked Discord; the alias is taken from the
    # player's registered roster name (never typed).
    ident = auth.current_identity(request)
    if not ident:
        raise HTTPException(403, "Your Discord must be linked to a roster to upload — ask staff.")
    alias = ident["display_name"]
    # bounded read: pull at most max+1 bytes so an oversized file can't exhaust memory
    data = await file.read(settings.demo_max_bytes + 1)
    if not data:
        raise HTTPException(400, "Empty file.")
    if len(data) > settings.demo_max_bytes:
        raise HTTPException(413, f"File exceeds the {settings.demo_max_bytes // (1024 * 1024)} MB limit.")
    orig = (_SAFE.sub("_", file.filename or "demo.dem") or "demo.dem")[:255]
    already_zip = data[:2] == b"PK" or orig.lower().endswith(".zip")  # accept .dem OR an existing zip

    schedule_id, bracket_mkey = _parse_match(match)
    demo_id = db.execute(
        "INSERT INTO lan_demos (alias, team_id, schedule_id, bracket_mkey, original_filename, note, uploaded_by, uploaded_ip) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (alias[:64], ident["team_id"], schedule_id, bracket_mkey, orig,
         (note or "").strip()[:255] or None, ident["discord_id"], common.client_ip(request)),
    )
    Path(settings.demo_dir).mkdir(parents=True, exist_ok=True)
    stored = f"{demo_id:06d}.zip"
    zpath = Path(settings.demo_dir) / stored
    if already_zip:
        zpath.write_bytes(data)  # already compressed — store as-is, no double-zip
    else:
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.writestr(orig, data)
    db.execute(
        "UPDATE lan_demos SET stored_name=%s, size_bytes=%s WHERE id=%s",
        (stored, zpath.stat().st_size, demo_id),
    )
    return RedirectResponse(request.url_for("demos"), status_code=303)


@router.get("/demos/{demo_id}/download")
def demos_download(demo_id: int):
    row = db.query_one(
        "SELECT alias, original_filename, stored_name FROM lan_demos WHERE id=%s", (demo_id,)
    )
    if not row or not row["stored_name"]:
        raise HTTPException(404, "Not found.")
    path = Path(settings.demo_dir) / row["stored_name"]
    if not path.is_file():
        raise HTTPException(404, "Stored file missing.")
    dl = _SAFE.sub("_", f"{row['alias']}_{row['original_filename']}")
    if not dl.lower().endswith(".zip"):
        dl += ".zip"
    return FileResponse(str(path), media_type="application/zip", filename=dl)
