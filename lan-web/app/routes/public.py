"""Public, no-auth routes."""
from fastapi import APIRouter, Request

from .. import auth
from ..templating import templates

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/")
def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "session_user": auth.session_user(request),
            "ident": auth.current_identity(request),
        },
    )
