#!/usr/bin/env python3
"""Generate thumbnails for photos uploaded before thumbnails existed.

Re-runnable: an existing thumbnail is left alone unless --force is given.

  python tools/backfill_thumbs.py [--force]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, photos  # noqa: E402


def main() -> int:
    force = "--force" in sys.argv
    rows = db.query_all("SELECT id, stored_name FROM lan_photos ORDER BY id")
    made = skipped = failed = 0
    for r in rows:
        name = r["stored_name"]
        if not name or name == "pending":
            continue
        if photos.has_thumb(name) and not force:
            print(f"  = {r['id']:>4} {name} (has one)")
            skipped += 1
            continue
        if photos.make(name):
            t = photos.thumb_path(name)
            src = Path(photos.settings.photo_dir) / name
            print(f"  + {r['id']:>4} {name} {src.stat().st_size:>9,} -> {t.stat().st_size:>7,}")
            made += 1
        else:
            print(f"  ! {r['id']:>4} {name} could not be thumbed")
            failed += 1
    print(f"made {made}, already had {skipped}, failed {failed}, of {len(rows)} rows")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
