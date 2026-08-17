"""The built WSDoD pages, served with the stats dataset withheld until it publishes.

The whole board is baked into the page as a JSON script block, and StaticFiles
ships a file byte-for-byte — so `stats_published` cannot hide anything from a
mount, and the CSS gate leaves the dataset one view-source away. These routes
are registered above the mounts and strip the bytes instead."""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from . import auth, seeding

FLAG = "stats_published"
# Philly 2025 ships its own board (#lan-data-2025) — a past event's published
# record, which this flag does not govern.
GATED_EDITION = "philly-2026"
STATS_BLOCKS = ("lan-data", "lanboard-data", "player-names")

# Deliberately the same shape the strip matches, so the check cannot disagree
# with it about what a block looks like.
_BLOCK = r'<script[^>]*\bid="%s"[^>]*>'
_SURVIVOR = re.compile(_BLOCK % ("(?:%s)" % "|".join(re.escape(b) for b in STATS_BLOCKS)))
_EDITIONS = re.compile(r'(<script[^>]*\bid="editions"[^>]*>)(.*?)(</script>)', re.S)
_BODY = re.compile(r"<body[^>]*>")

_HEADERS = {
    # The gate turns on a session cookie, so a shared cache holding one variant
    # would hand a stripped page to staff or the dataset to the public.
    "Cache-Control": "private, no-store",
    "Vary": "Cookie",
}


class GateFailure(RuntimeError):
    """The strip did not take. Serving the page anyway is the fail-open bug."""


def _drop_blocks(html: str) -> str:
    for name in STATS_BLOCKS:
        html = re.sub(_BLOCK % re.escape(name) + r".*?</script>\n?", "", html, flags=re.S)
    return html


def _close_edition_flag(html: str) -> str:
    """The page re-applies its own gate from #editions on load, so stripping the
    data without this leaves an empty board that reads as nobody scored."""
    def sub(m):
        try:
            eds = json.loads(m.group(2))
        except ValueError:
            return m.group(0)
        ed = eds.get("editions", {}).get(GATED_EDITION)
        if not isinstance(ed, dict) or "statsPublished" not in ed:
            return m.group(0)
        ed["statsPublished"] = False
        return m.group(1) + json.dumps(eds, ensure_ascii=False, separators=(",", ":")) + m.group(3)
    return _EDITIONS.sub(sub, html)


def _close_body_flag(html: str) -> str:
    """Readers without JS get the same page — the CSS gate keys off this."""
    def sub(m):
        tag = m.group(0)
        if f'data-edition="{GATED_EDITION}"' not in tag:
            return tag
        return tag.replace('data-stats="on"', 'data-stats="off"')
    return _BODY.sub(sub, html, count=1)


def _verify(html: str) -> None:
    left = _SURVIVOR.search(html)
    if left:
        raise GateFailure(f"stats block survived the strip: {left.group(0)[:80]}")
    m = _EDITIONS.search(html)
    if m:
        try:
            ed = json.loads(m.group(2)).get("editions", {}).get(GATED_EDITION) or {}
        except ValueError:
            ed = {}
        if ed.get("statsPublished"):
            raise GateFailure("#editions still publishes the board")
    body = _BODY.search(html)
    if body and f'data-edition="{GATED_EDITION}"' in body.group(0) \
            and 'data-stats="on"' in body.group(0):
        raise GateFailure("body still carries data-stats=on")


def withhold(html: str) -> str:
    """The page minus its stats dataset, or GateFailure — never a page that only
    looks stripped."""
    out = _close_body_flag(_close_edition_flag(_drop_blocks(html)))
    _verify(out)
    return out


_cache: dict[tuple[str, bool], tuple[tuple[int, int], bytes]] = {}


def page_bytes(path: Path, gated: bool) -> bytes:
    """Memoized on the file's stamp and the gate state, so a rebuild or a publish
    flip invalidates and a request does not."""
    key = (str(path), gated)
    st = path.stat()
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    raw = path.read_text(encoding="utf-8")
    out = (withhold(raw) if gated else raw).encode("utf-8")
    _cache[key] = (stamp, out)
    return out


def is_gated(request: Request) -> bool:
    """Staff read an unpublished board; everyone else waits. Fails closed — a DB
    blip serves the public page, never the dataset."""
    try:
        published = seeding.is_published(FLAG)
    except Exception:
        published = False
    if published:
        return False
    try:
        return not auth.is_admin(request)
    except Exception:
        return True


def _handler(path: Path):
    def page(request: Request):
        try:
            body = page_bytes(path, is_gated(request))
        except GateFailure:
            return PlainTextResponse("This page is temporarily unavailable.",
                                     status_code=503, headers=_HEADERS)
        return HTMLResponse(body, headers=_HEADERS)
    return page


def entry_urls(path: Path, site_dir: Path) -> list[str]:
    """Both URLs an html=True mount answers a page on — the file and, for an
    index, the directory it stands for."""
    rel = path.relative_to(site_dir).as_posix()
    urls = ["/" + rel]
    if path.name == "index.html":
        urls.append("/" + rel[: -len("index.html")])
    return urls


def register(app: FastAPI, site_dir: Path, mount: str, at_root: bool) -> None:
    """Every HTML entry point the mounts would otherwise serve. One missed path
    is a way around the gate, so this walks the tree rather than listing paths —
    at startup, so a rebuild that adds a page needs a restart to be covered."""
    prefixes = [mount.rstrip("/")]
    if at_root:
        prefixes.append("")
    # "*.html*", not "*.html": a deploy backup left in the docroot
    # (index.html.bak-…) is a second, ungated copy of the same page, and
    # StaticFiles serves any file it finds.
    for path in sorted(site_dir.rglob("*.html*")):
        for url in entry_urls(path, site_dir):
            for prefix in prefixes:
                app.add_api_route(
                    prefix + url, _handler(path), methods=["GET"],
                    response_class=HTMLResponse, include_in_schema=False,
                    name=f"wsdod_page:{prefix}{url}",
                )
