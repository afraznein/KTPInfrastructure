"""WSDoD LAN 2026 web service — app entry.

Run (dev):  uvicorn app.main:app --reload --port 8099
Behind nginx at /lan/ set LAN_WEB_ROOT_PATH=/lan."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .routes import (admin_routes, auth_routes, bracket_routes, checkin_routes,
                     demo_routes, extras_routes, mappoll_routes, placements_routes,
                     poll_routes, public, schedule_routes, stations_routes,
                     veto_routes)

app = FastAPI(title="WSDoD LAN 2026", root_path=settings.root_path)

# Session cookie carries the Discord identity + OAuth state. Secure-only in prod
# (TLS terminated at nginx); lax so the OAuth top-level redirect carries it back.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    https_only=settings.is_prod,
    same_site="lax",
)

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
    name="static",
)

app.include_router(public.router)
app.include_router(auth_routes.router)
app.include_router(poll_routes.router)
app.include_router(mappoll_routes.router)
app.include_router(schedule_routes.router)
app.include_router(bracket_routes.router)
app.include_router(veto_routes.router)
app.include_router(stations_routes.router)
app.include_router(placements_routes.router)
app.include_router(checkin_routes.router)
app.include_router(demo_routes.router)
app.include_router(extras_routes.router)
app.include_router(admin_routes.router)
