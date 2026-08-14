"""The frozen match-key → slug map, read from the build's match-slugs.json.

Read at runtime rather than copied in: the file is the freeze, and a second
copy of it is a second thing that can be regenerated out from under a shared
Discord link. A missing or malformed file leaves an empty map, so the redirect
404s rather than the app failing to start."""
from __future__ import annotations

import json
from pathlib import Path

from . import config

_cache: tuple[tuple | None, dict[str, str]] = (None, {})


def _pairs(data) -> list[tuple[str, str]]:
    """Every shape the freeze has plausibly been written in.

    The file is generated elsewhere and its layout is not this module's to
    choose; guessing one shape and 404ing on the others would look exactly like
    a missing file."""
    if isinstance(data, dict):
        for key in ("matches", "slugs", "match_slugs"):
            inner = data.get(key)
            if isinstance(inner, (dict, list)):
                return _pairs(inner)
        out = []
        for k, v in data.items():
            if isinstance(v, str):
                out.append((k, v))
            elif isinstance(v, dict) and isinstance(v.get("slug"), str):
                out.append((k, v["slug"]))
        return out
    if isinstance(data, list):
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            key = next((item[k] for k in ("match_key", "key", "match")
                        if isinstance(item.get(k), str)), None)
            if key and isinstance(item.get("slug"), str):
                out.append((key, item["slug"]))
        return out
    return []


def load() -> dict[str, str]:
    """Memoized on the file's stamp, so a regenerated map is picked up without
    a restart and a request does not re-read it."""
    global _cache
    path = Path(config.settings.match_slugs_path)
    try:
        st = path.stat()
    except OSError:
        _cache = (None, {})
        return {}
    # Path included, so pointing the setting at a different file invalidates —
    # two generated maps can share a size and a timestamp.
    stamp = (str(path), st.st_mtime_ns, st.st_size)
    if _cache[0] == stamp:
        return _cache[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    out = {k: v for k, v in _pairs(data) if k and v}
    _cache = (stamp, out)
    return out


def slug_for(match_key: str) -> str | None:
    """The slug a raw key redirects to.

    A key that is already a slug resolves to itself: this route sits above the
    static mount, so without that a shared /match/<slug> — the one URL people
    actually paste, minus its trailing slash — would 404 on the way to the page
    that exists."""
    slugs = load()
    if match_key in slugs:
        return slugs[match_key]
    return match_key if match_key in set(slugs.values()) else None
