"""League alias by SteamID, for naming players in the private connection rows.

Ruled 2026-10-25 (drew, coordination netcode-player-settings): netcode reports name a
player by their LEAGUE ALIAS -- SteamID -> ktp.player_steam (status current) ->
ktp.player.alias -- with the in-game name beside it; a SteamID with no current link
is "not a league player". Both tables carry a public SELECT policy.

Read with the same KTP_SUPABASE_URL / KTP_SUPABASE_SECRET_KEY the report service
already has for report_sync (/etc/ktp/reports.env). Read-only. Fetched once per
process. Any failure -- no env, network, HTTP error -- returns an empty map and a
reason, so a report never fails or stalls on the website being down: its rows then
read `league_alias: null, league_registered: null` (unknown), never false.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

STEAM64_BASE = 76561197960265728
PAGE = 1000
_CACHE: tuple[dict[str, str], str | None] | None = None


def steam64(steam_id: str | None) -> str | None:
    """`STEAM_0:Y:Z` or the roster's bare `Y:Z` -> SteamID64; None for bots and junk."""
    if not steam_id:
        return None
    parts = str(steam_id).split(":")
    if len(parts) == 3 and parts[0].startswith("STEAM_"):
        parts = parts[1:]
    if len(parts) != 2 or not all(p.isdigit() for p in parts) or parts[0] not in ("0", "1"):
        return None
    return str(STEAM64_BASE + int(parts[1]) * 2 + int(parts[0]))


def _get_all(base: str, key: str, table: str, select: str, order: str) -> list[dict]:
    rows, offset = [], 0
    while True:
        req = urllib.request.Request(
            f"{base}/rest/v1/{table}?select={select}&order={order}&limit={PAGE}&offset={offset}",
            headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept-Profile": "ktp"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = json.loads(resp.read())
        rows += page
        if len(page) < PAGE:
            return rows
        offset += PAGE


def load() -> tuple[dict[str, str], str | None]:
    """(steam64 -> alias, None) on success; ({}, reason) when the registry is unreachable."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    base, key = os.environ.get("KTP_SUPABASE_URL", "").rstrip("/"), os.environ.get("KTP_SUPABASE_SECRET_KEY", "")
    if not base or not key:
        _CACHE = ({}, "KTP_SUPABASE_URL / KTP_SUPABASE_SECRET_KEY not set")
        return _CACHE
    try:
        alias = {p["id"]: p["alias"] for p in _get_all(base, key, "player", "id,alias", "id")}
        links = _get_all(base, key, "player_steam", "player_id,steam_id64,status", "player_id")
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, KeyError) as exc:
        _CACHE = ({}, f"league registry unreachable: {type(exc).__name__}")
        return _CACHE
    _CACHE = ({str(r["steam_id64"]): alias[r["player_id"]] for r in links
               if r.get("status") == "current" and r.get("player_id") in alias}, None)
    return _CACHE
