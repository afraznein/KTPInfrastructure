#!/usr/bin/env python3
"""Reset the LAN site to a clean slate for the real event.

Wipes all preview/test competition data AND uploaded files, while PRESERVING the
registered teams, players, and staff access. Run before real seeding.

  python tools/reset_for_event.py          # dry run — shows what it would clear
  python tools/reset_for_event.py --yes    # actually do it

Preserved: lan_teams (seed reset to NULL), lan_players, lan_admins.
Cleared:   schedule, bracket, ballots, stations, streams, awards + votes,
           result audit, photos, demos, the preview/announcement settings, and
           every file under the photo + demo upload dirs. The poll is closed so
           staff reopen it deliberately for real ballots.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for `app`

from app import db
from app.config import settings

WIPE_TABLES = [
    "lan_schedule", "lan_bracket", "lan_seed_ballots", "lan_map_skip_ballots",
    "lan_stations", "lan_streams", "lan_award_votes", "lan_awards",
    "lan_result_audit", "lan_photos", "lan_demos",
]
WIPE_SETTINGS = ["playoff_seeds", "preview_banner", "final_placements",
                 "announcement", "gf_advantage", "skip_map"]


def _counts():
    out = {}
    for t in WIPE_TABLES:
        try:
            out[t] = db.query_one(f"SELECT COUNT(*) AS c FROM {t}")["c"]
        except Exception:
            out[t] = "—"  # table not present yet
    return out


def _upload_files():
    files = []
    for d in (Path(settings.photo_dir), Path(settings.demo_dir)):
        if d.is_dir():
            files += [p for p in d.iterdir() if p.is_file()]
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="actually perform the reset")
    a = ap.parse_args()

    counts, files = _counts(), _upload_files()
    print("Would clear:")
    for t, n in counts.items():
        print(f"  {t:<18} {n} rows")
    print(f"  settings           {', '.join(WIPE_SETTINGS)}")
    print(f"  upload files       {len(files)} (photos + demos)")
    print("Preserved: lan_teams (seed reset to NULL), lan_players, lan_admins.")

    if not a.yes:
        print("\nDry run — re-run with --yes to perform the reset.")
        return 0

    with db.get_conn() as conn, conn.cursor() as cur:
        for t in WIPE_TABLES:
            try:
                cur.execute(f"DELETE FROM {t}")
            except Exception as e:
                print(f"  skip {t}: {e}")
        cur.execute("UPDATE lan_teams SET seed=NULL")
        ph = ",".join(["%s"] * len(WIPE_SETTINGS))
        cur.execute(f"DELETE FROM lan_settings WHERE k IN ({ph})", tuple(WIPE_SETTINGS))
        cur.execute("INSERT INTO lan_settings (k, v) VALUES ('poll_open','0') "
                    "ON DUPLICATE KEY UPDATE v='0'")
        cur.execute("INSERT INTO lan_settings (k, v) VALUES ('map_skip_poll_open','0') "
                    "ON DUPLICATE KEY UPDATE v='0'")

    removed = 0
    for p in files:
        try:
            p.unlink(); removed += 1
        except Exception as e:
            print(f"  could not remove {p}: {e}")

    print(f"\nDone — cleared {len(WIPE_TABLES)} tables, reset seeds, closed the poll, "
          f"removed {removed} upload files.")
    print("Teams, players and staff access preserved. Reopen the poll when ready for real ballots.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
