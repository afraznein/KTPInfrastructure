#!/usr/bin/env python3
"""Seed the voted award categories from the site's own awards.json.

The categories are read from the published data rather than retyped, so the
ballot on the site and the ballot in the database cannot drift apart. Existing
rows are matched on slug and left alone -- re-running only fills gaps.

  python tools/seed_awards.py <path-to-awards.json> [--open]

--open sets is_open on the seeded categories. Without it they are created
closed, which is the safe default: a category with is_open=0 rejects votes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        return print(__doc__) or 2
    want_open = "--open" in sys.argv
    data = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    cats = data.get("vote") or []
    if not cats:
        return print("no 'vote' categories in that file") or 1

    have = {r["slug"]: r for r in db.query_all("SELECT id, slug, is_open FROM lan_awards")}
    for i, c in enumerate(cats):
        slug, title = c["slug"], c["title"]
        if slug in have:
            print(f"  = {slug:10} exists (id {have[slug]['id']})")
        else:
            db.execute(
                "INSERT INTO lan_awards (slug, title, kind, sort_order) VALUES (%s,%s,'player',%s)",
                (slug, title[:96], i),
            )
            print(f"  + {slug:10} created — {title}")
    if want_open:
        slugs = [c["slug"] for c in cats]
        marks = ",".join(["%s"] * len(slugs))
        db.execute(f"UPDATE lan_awards SET is_open=1 WHERE slug IN ({marks})", tuple(slugs))
        print(f"  opened {len(slugs)} categories")

    for r in db.query_all("SELECT slug, title, kind, is_open FROM lan_awards ORDER BY sort_order, id"):
        print(f"  {'OPEN  ' if r['is_open'] else 'closed'} {r['slug']:10} {r['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
