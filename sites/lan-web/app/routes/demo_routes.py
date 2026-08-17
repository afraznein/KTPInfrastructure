"""Demo / VOD archive. Uploads are zipped server-side (DoD .dem compresses hard)
and require the uploader's alias. Download serves the stored zip."""
import re
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .. import auth, common, db, demos, parse
from ..config import settings
from ..templating import templates

router = APIRouter()
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _parse_match(raw: str):
    """'sat:123' / 'bkt:QF1' / 'gen:draft' -> (schedule_id, bracket_mkey, category).

    A gen: value is whitelisted here rather than trusted from the form — it is
    written straight into an ENUM column, and an out-of-range value would be a
    STRICT_TRANS_TABLES error on insert."""
    raw = (raw or "").strip()
    sched_id = parse.as_int(raw[4:]) if raw.startswith("sat:") else None
    if sched_id is not None:
        return sched_id, None, "match"
    if raw.startswith("bkt:") and raw[4:]:
        return None, raw[4:][:8], "match"
    if raw.startswith("gen:") and raw[4:] in demos.GENERIC:
        return None, None, raw[4:]
    return None, None, "match"


@router.get("/demos", name="demos")
def demos_page(request: Request, team: int | None = None):
    rows = demos.listing(team)
    ident = auth.current_identity(request)
    my_matches = (demos.team_matches(ident["team_id"]) + demos.generic_options()) if ident else []
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

    schedule_id, bracket_mkey, category = _parse_match(match)
    demo_id = db.execute(
        "INSERT INTO lan_demos (alias, team_id, schedule_id, bracket_mkey, category, "
        "original_filename, note, uploaded_by, uploaded_ip) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (alias[:64], ident["team_id"], schedule_id, bracket_mkey, category, orig,
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
    if common.wants_json(request):
        return JSONResponse({"ok": True, "id": demo_id})
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
