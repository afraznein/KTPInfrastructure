"""Best-effort Discord DMs to team captains (e.g. "you're up on Server 3").

Uses a bot token (LAN_DISCORD_BOT_TOKEN) — the bot must share a guild with the
captain, which KTPAdminBot already does. No token set → silently no-ops. Network
or API failures are swallowed: a notification must never break a staff action."""
from __future__ import annotations

import json
import urllib.request

from .config import settings

_API = "https://discord.com/api/v10"


def _post(path: str, token: str, payload: dict) -> dict:
    req = urllib.request.Request(
        _API + path,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "KTP-LAN/1.0 (+https://wsdod)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=6) as r:
        return json.loads(r.read().decode() or "{}")


def _dm(discord_id, content: str, token: str) -> None:
    chan = _post("/users/@me/channels", token, {"recipient_id": str(discord_id)})
    _post(f"/channels/{chan['id']}/messages", token, {"content": content})


def notify_captains(team_ids, content: str) -> int:
    """DM each given team's captain. Returns how many were sent. Never raises."""
    token = settings.discord_bot_token
    if not token:
        return 0
    from . import db
    sent = 0
    for tid in team_ids:
        if not tid:
            continue
        try:
            cap = db.query_one(
                "SELECT discord_id FROM lan_players "
                "WHERE team_id=%s AND is_captain=1 AND discord_id IS NOT NULL LIMIT 1",
                (tid,),
            )
            if cap and cap["discord_id"]:
                _dm(cap["discord_id"], content, token)
                sent += 1
        except Exception:
            pass  # best-effort; never let a DM failure surface to the admin
    return sent
