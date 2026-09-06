"""Fleet status poller.

One poll for all viewers: a systemd timer runs this on the data server, it
queries the 24 instances once, and writes a small JSON the page serves as a
static file. The alternative -- querying from the browser -- would fan 24 UDP
round-trips out per visitor and expose the fleet's addressing to anyone with
devtools.

Two properties keep the page honest:

A single missed reply is NOT down. A healthy Atlanta instance timed out at 1.5s
during a sweep that returned 24/24 at 2.0s, so one miss means "slow", and only
DOWN_AFTER consecutive misses flips a server to down.

Staleness is a state, not an absence. If this poller dies, the JSON it already
wrote stays on disk and would otherwise render as a healthy fleet forever. Every
document carries `generated` and the page treats an old one as unknown.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .a2s import A2SError, count_hltv, count_humans, query, query_players
from .hostname import parse

DOWN_AFTER = 3          # consecutive failed polls before a server reads "down"
POLL_TIMEOUT = 2.5
MAX_WORKERS = 12

# hud-observer's HQ projection, on the same box. Localhost-only: :3001 is plain
# HTTP with no auth, so this poller is the one thing allowed to consume it --
# the public site gets the merged, allowlisted result over HTTPS instead.
HUD_HQ_URL = "http://127.0.0.1:3001/api/hq"
HUD_TIMEOUT = 3.0
HUD_ROSTER_CAP = 16


@dataclass(frozen=True)
class Instance:
    region: str
    label: str
    ip: str
    port: int


def fleet() -> list[Instance]:
    hosts = [
        ("Atlanta", "74.91.121.9", 5),
        ("Dallas", "74.91.126.55", 5),
        ("Denver", "66.163.114.109", 5),
        ("New York", "74.91.123.64", 5),
        ("Chicago", "172.238.176.101", 4),
    ]
    return [
        Instance(region, f"{region} {n + 1}", ip, 27015 + n)
        for region, ip, count in hosts
        for n in range(count)
    ]


@dataclass
class _Streak:
    misses: int = 0
    last_ok: float | None = None


_streaks: dict[str, _Streak] = {}


def _poll_one(inst: Instance) -> dict:
    key = f"{inst.ip}:{inst.port}"
    streak = _streaks.setdefault(key, _Streak())
    try:
        info = query(inst.ip, inst.port, POLL_TIMEOUT)
    except A2SError as exc:
        streak.misses += 1
        return {
            "instance": inst,
            "up": streak.misses < DOWN_AFTER,
            "degraded": True,
            "misses": streak.misses,
            "error": str(exc),
            "last_ok": streak.last_ok,
        }
    streak.misses, streak.last_ok = 0, time.time()

    # A2S's player count includes the HLTV proxy, so it never reads 0 on a live
    # instance. Ask for the roster and count actual people; if that second query
    # fails, fall back rather than losing the whole server from the page.
    try:
        roster = query_players(inst.ip, inst.port, POLL_TIMEOUT)
        humans, proxies = count_humans(roster), count_hltv(roster)
    except A2SError:
        humans, proxies = None, 0

    return {
        "instance": inst,
        "up": True,
        "degraded": False,
        "misses": 0,
        "info": info,
        "name": parse(info.hostname),
        "humans": humans,
        "hltv": proxies,
        "last_ok": streak.last_ok,
    }


def poll_fleet(instances: list[Instance] | None = None) -> list[dict]:
    instances = instances or fleet()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        return list(pool.map(_poll_one, instances))


def fetch_hud(url: str = HUD_HQ_URL, timeout: float = HUD_TIMEOUT) -> dict[str, dict]:
    """hud-observer's /api/hq, keyed by BASE hostname ("KTP - Atlanta 1").

    Keying goes through hostname.parse() because KTPMatchHandler renames a
    server mid-match; whichever form the hud feed reports, the base is what
    matches the fleet. Empty dict on ANY failure -- the hud backend being down
    must cost the status page nothing but the match blocks.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            doc = json.load(resp)
    except Exception:
        return {}
    servers = doc.get("servers") if isinstance(doc, dict) else None
    if not isinstance(servers, list):
        return {}
    out: dict[str, dict] = {}
    for entry in servers:
        if not isinstance(entry, dict):
            continue
        hostname = entry.get("hostname")
        if not isinstance(hostname, str) or not hostname.strip():
            continue
        out[parse(hostname).base or hostname.strip()] = entry
    return out


def _hud_int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _hud_roster(players) -> list[dict]:
    if not isinstance(players, list):
        return []
    roster = []
    for p in players[:HUD_ROSTER_CAP]:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        roster.append({
            "name": name.strip()[:64],
            "kills": _hud_int(p.get("kills")) or 0,
            "deaths": _hud_int(p.get("deaths")) or 0,
        })
    return roster


def _hud_match(h: dict) -> dict:
    """Allowlist one hud entry down to what the public page renders.

    Names and scores are published on purpose (operator decision 2026-08-22:
    no spoiler gate -- the feed is already broadcast-delayed ~60s, which is the
    anti-ghosting measure). Everything else stays out by construction: match
    ids, event counters, user_id, flag topology, and whatever the hud backend
    grows next.
    """
    status = h.get("status")
    phase = h.get("phase")
    timeleft = h.get("timeleft")
    return {
        "status": status if isinstance(status, str) else None,
        "phase": phase if isinstance(phase, str) else None,
        "half": _hud_int(h.get("half")),
        "allies_score": _hud_int(h.get("alliesScore")),
        "axis_score": _hud_int(h.get("axisScore")),
        "timeleft": timeleft if isinstance(timeleft, (int, float))
        and not isinstance(timeleft, bool) else None,
        "timer_frozen": h.get("timerFrozen") is True,
        "delay_seconds": _hud_int(h.get("delaySeconds")),
        "allies": _hud_roster(h.get("allies")),
        "axis": _hud_roster(h.get("axis")),
    }


def public_document(
    results: list[dict], now: float | None = None,
    hud: dict[str, dict] | None = None,
) -> dict:
    """Build the logged-out view.

    Allowlisted by construction: this function names every field it emits, so a
    field added upstream cannot leak by default. IPs, ports, miss counts and
    error strings are fleet topology and deliberately absent. The hud merge
    goes through the same discipline in _hud_match.
    """
    servers = []
    for r in results:
        inst: Instance = r["instance"]
        entry = {"region": inst.region, "label": inst.label, "up": bool(r["up"])}
        # The game endpoint is public by nature -- players type it into the
        # console to join. This is the ONE address the public document carries,
        # and it is deliberate; everything else about topology stays out.
        entry["connect"] = f"{inst.ip}:{inst.port}"
        if not r["degraded"]:
            info, name = r["info"], r["name"]
            entry["map"] = info.map
            # Roster count when we have it; the A2S slot count only as a fallback,
            # and that one still includes HLTV.
            humans = r.get("humans")
            entry["players"] = info.humans if humans is None else humans
            # An HLTV proxy holds a real slot, so advertising the raw A2S max
            # overstates how many people can actually join. Report the human
            # capacity and flag the proxy separately -- the page renders "0/12 +H".
            #
            # The slot is reserved whether or not a proxy answers right now.
            # Subtracting only the OBSERVED proxies made capacity flip to 13
            # every time the proxies bounced -- and `hltv-restart.timer` bounces
            # all 24 of them at 03:00 and 11:00 daily, so a status page would
            # have advertised a 13th seat twice a day that nothing can keep.
            # Every fleet instance is permanently paired with a proxy, so one
            # slot is never a human's. Operator's call 2026-08-07: show /12.
            proxies = r.get("hltv", 0)
            entry["max_players"] = max(0, info.max_players - max(proxies, 1))
            # Flag stays observation-driven: capacity is what you can join,
            # this is whether the proxy is actually attached right now.
            if proxies:
                entry["hltv"] = True
            if name.match_type:
                entry["match_type"] = name.match_type
                entry["state"] = name.state
        # Fleet hostnames follow "KTP - {label}", which is also how the hud
        # feed identifies servers -- so coverage scales by itself: an instance
        # that starts reporting simply appears in `hud` and attaches here.
        h = (hud or {}).get(f"KTP - {inst.label}")
        if isinstance(h, dict) and h.get("online") is True:
            entry["match"] = _hud_match(h)
        servers.append(entry)
    up = sum(1 for s in servers if s["up"])
    return {
        "generated": int(now or time.time()),
        "servers": servers,
        "summary": {"up": up, "total": len(servers),
                    "players": sum(s.get("players", 0) for s in servers)},
    }


def detail_document(results: list[dict], now: float | None = None) -> dict:
    """Full operator view -- written outside the web root, served only to admins."""
    return {
        "generated": int(now or time.time()),
        "servers": [
            {
                "label": r["instance"].label,
                "address": f"{r['instance'].ip}:{r['instance'].port}",
                "up": bool(r["up"]),
                "degraded": bool(r["degraded"]),
                "consecutive_misses": r["misses"],
                "last_ok": r["last_ok"],
                "error": r.get("error"),
                "hostname": r["info"].hostname if not r["degraded"] else None,
            }
            for r in results
        ],
    }


def write_atomic(path: str, doc: dict, mode: int = 0o600) -> None:
    """Never let a reader see a half-written document.

    `mode` is explicit because mkstemp creates 0600 and the two documents have
    opposite audiences: nginx serves public.json directly, so it must be
    world-readable, while detail.json carries addresses and must not be.
    """
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, separators=(",", ":"))
        os.chmod(tmp, mode)          # before the rename, so no window is 0600
        os.replace(tmp, path)
    except BaseException:
        os.path.exists(tmp) and os.unlink(tmp)
        raise


PUSH_TIMEOUT = 8.0


def push_public(
    doc: dict,
    url: str,
    secret: str,
    timeout: float = PUSH_TIMEOUT,
) -> tuple[bool, str]:
    """POST the public document to ktpleague.gg. Returns (ok, detail).

    The site used to fetch public.json off support.ktpdod.com at render time.
    Pushing instead is what lets that vhost be decommissioned -- the poll still
    happens here, because A2S is UDP and cannot run in a serverless render.

    Raises nothing: a push failure must not lose the poll we already wrote to
    disk. The caller decides what a failure means.
    """
    body = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    try:
        # Inside the try: Request() validates the URL in its constructor and
        # raises ValueError on a malformed one, so a typo in SUPPORT_PUSH_URL
        # would otherwise crash a poll that had already succeeded.
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-internal-status": secret,
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                return True, f"HTTP {resp.status}"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        # 503 means the site has no secret configured; 401 means ours is wrong.
        # Both are operator errors and neither is retryable, so say which.
        return False, f"HTTP {exc.code}"
    except Exception as exc:                       # noqa: BLE001 - reported, not swallowed
        return False, f"{type(exc).__name__}: {exc}"
