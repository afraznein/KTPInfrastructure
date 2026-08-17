"""Raw match keys, redirected to the frozen slug their page lives at."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import match_slugs

router = APIRouter()


@router.get("/match/{match_key}", name="match_key_redirect", include_in_schema=False)
def match_key_redirect(request: Request, match_key: str):
    """`/match/1785715972-KTP1` → `/match/<slug>/`, so a link that predates the
    slugs keeps working.

    302, not 301: the map is generated, and a permanent redirect to a wrong
    slug outlives every correction we could make to the file."""
    slug = match_slugs.slug_for(match_key)
    if not slug:
        raise HTTPException(404, "No page for that match.")
    # Behind nginx at /lan the app never sees that prefix on the way in, so a
    # bare path in a Location header sends the reader to the wrong host root.
    root = request.scope.get("root_path", "").rstrip("/")
    return RedirectResponse(f"{root}/match/{slug}/", status_code=302)
