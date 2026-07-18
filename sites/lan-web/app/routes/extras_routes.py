"""Post-event extras: awards voting and the photo gallery."""
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from .. import auth, awards, common, db
from ..config import settings
from ..templating import templates

router = APIRouter()
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_IMG_EXT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif"}


# ── awards ───────────────────────────────────────────────────────────────
@router.get("/awards", name="awards")
def awards_page(request: Request):
    is_admin = auth.is_admin(request)
    ident = auth.current_identity(request)
    voter = ident["discord_id"] if ident else None
    mine = awards.my_votes(voter)
    items = []
    for a in awards.all_awards():
        show_results = bool(is_admin or not a["is_open"])
        items.append({
            "id": a["id"], "slug": a["slug"], "title": a["title"], "kind": a["kind"],
            "is_open": a["is_open"], "options": awards.targets(a["kind"]),
            "my_vote": mine.get(a["id"]),
            "results": awards.results(a) if show_results else None,
            "total": awards.total_votes(a["id"]),
            "show_results": show_results,
        })
    ctx = common.base_ctx(request, "awards")
    ctx.update(awards=items, is_admin=is_admin,
               can_vote=ident is not None, logged_in=ctx["session_user"] is not None)
    return templates.TemplateResponse(request, "awards.html", ctx)


@router.post("/awards/vote", name="award_vote")
async def award_vote(request: Request):
    ident = auth.require_login(request)
    f = await request.form()
    try:
        awards.cast_vote(int(f["award_id"]), ident["discord_id"], int(f["target_id"]))
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(request.url_for("awards"), status_code=303)


@router.post("/admin/awards/add", name="award_add")
async def award_add(request: Request):
    auth.require_admin(request)
    f = await request.form()
    title = (f.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Award title required.")
    slug = _SAFE.sub("-", (f.get("slug") or title).strip().lower())[:48] or "award"
    kind = "team" if (f.get("kind") == "team") else "player"
    try:
        db.execute(
            "INSERT INTO lan_awards (slug, title, kind, sort_order) VALUES (%s,%s,%s,%s)",
            (slug, title[:96], kind, int(f.get("sort_order") or 0)),
        )
    except Exception:
        raise HTTPException(400, f"Could not add (slug {slug!r} may already exist).")
    return RedirectResponse(request.url_for("awards"), status_code=303)


@router.post("/admin/awards/toggle", name="award_toggle")
async def award_toggle(request: Request):
    auth.require_admin(request)
    f = await request.form()
    db.execute("UPDATE lan_awards SET is_open = 1 - is_open WHERE id=%s", (int(f["award_id"]),))
    return RedirectResponse(request.url_for("awards"), status_code=303)


@router.post("/admin/awards/delete", name="award_delete")
async def award_delete(request: Request):
    auth.require_admin(request)
    f = await request.form()
    aid = int(f["award_id"])
    db.execute("DELETE FROM lan_award_votes WHERE award_id=%s", (aid,))
    db.execute("DELETE FROM lan_awards WHERE id=%s", (aid,))
    return RedirectResponse(request.url_for("awards"), status_code=303)


# ── photo gallery ────────────────────────────────────────────────────────
@router.get("/gallery", name="gallery")
def gallery_page(request: Request):
    # Admins see the upload audit (who + IP); the roster name resolves it where
    # the uploader is on a team, otherwise the stored Discord name stands in.
    rows = db.query_all(
        "SELECT ph.*, p.display_name AS roster_name FROM lan_photos ph "
        "LEFT JOIN lan_players p ON p.discord_id = ph.uploaded_by "
        "ORDER BY ph.uploaded_at DESC, ph.id DESC"
    )
    ctx = common.base_ctx(request, "gallery")
    ctx.update(photos=rows, can_upload=auth.session_user(request) is not None,
               is_admin=auth.is_admin(request),
               max_mb=settings.photo_max_bytes // (1024 * 1024))
    return templates.TemplateResponse(request, "gallery.html", ctx)


@router.post("/gallery/upload", name="gallery_upload")
async def gallery_upload(request: Request, file: UploadFile = File(...), caption: str = Form("")):
    su = auth.session_user(request)
    if not su:
        raise HTTPException(403, "Sign in with Discord to post photos.")
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in _IMG_EXT:
        raise HTTPException(400, "Image must be jpg, png, webp, or gif.")
    data = await file.read(settings.photo_max_bytes + 1)
    if not data:
        raise HTTPException(400, "Empty file.")
    if len(data) > settings.photo_max_bytes:
        raise HTTPException(413, f"Image exceeds the {settings.photo_max_bytes // (1024*1024)} MB limit.")
    pid = db.execute(
        "INSERT INTO lan_photos (stored_name, caption, uploaded_by, uploaded_ip, uploaded_name) "
        "VALUES (%s,%s,%s,%s,%s)",
        ("pending", (caption or "").strip()[:200] or None,
         su["discord_id"], common.client_ip(request), (su.get("discord_name") or "")[:64] or None),
    )
    Path(settings.photo_dir).mkdir(parents=True, exist_ok=True)
    stored = f"{pid:06d}.{ext}"
    (Path(settings.photo_dir) / stored).write_bytes(data)
    db.execute("UPDATE lan_photos SET stored_name=%s WHERE id=%s", (stored, pid))
    return RedirectResponse(request.url_for("gallery"), status_code=303)


@router.get("/gallery/{photo_id}/img", name="gallery_img")
def gallery_img(photo_id: int):
    row = db.query_one("SELECT stored_name FROM lan_photos WHERE id=%s", (photo_id,))
    if not row or not row["stored_name"] or row["stored_name"] == "pending":
        raise HTTPException(404, "Not found.")
    path = Path(settings.photo_dir) / row["stored_name"]
    if not path.is_file():
        raise HTTPException(404, "Stored file missing.")
    ext = row["stored_name"].rsplit(".", 1)[-1].lower()
    return FileResponse(str(path), media_type=_IMG_EXT.get(ext, "application/octet-stream"))


@router.post("/admin/gallery/delete", name="gallery_delete")
async def gallery_delete(request: Request):
    auth.require_admin(request)
    f = await request.form()
    pid = int(f["photo_id"])
    row = db.query_one("SELECT stored_name FROM lan_photos WHERE id=%s", (pid,))
    if row and row["stored_name"]:
        p = Path(settings.photo_dir) / row["stored_name"]
        if p.is_file():
            p.unlink()
    db.execute("DELETE FROM lan_photos WHERE id=%s", (pid,))
    return RedirectResponse(request.url_for("gallery"), status_code=303)
