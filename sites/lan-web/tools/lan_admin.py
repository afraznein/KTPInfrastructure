#!/usr/bin/env python3
"""Phase-0 admin CLI: populate LAN teams/players until the admin UI lands.

  python tools/lan_admin.py add-team   --name "Money Crew" --tag MC
  python tools/lan_admin.py add-player  --team "Money Crew" --display ck \
        --discord 123456789012345678 --discord-name ck --steam "STEAM_0:1:1" --captain
  python tools/lan_admin.py list

Linking your own --discord ID to a player is how you exercise the OAuth →
identity path before real rosters exist."""
import argparse
import sys

from app import db


def add_team(a):
    tid = db.execute("INSERT INTO lan_teams (name, tag) VALUES (%s, %s)", (a.name, a.tag))
    print(f"team #{tid}: {a.name}")


def add_player(a):
    team = db.query_one("SELECT id FROM lan_teams WHERE name=%s", (a.team,))
    if not team:
        sys.exit(f"no team named {a.team!r} — add it first with add-team")
    pid = db.execute(
        "INSERT INTO lan_players (team_id, discord_id, discord_name, steam_id, display_name, is_captain) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (team["id"], a.discord, a.discord_name, a.steam, a.display, 1 if a.captain else 0),
    )
    print(f"player #{pid}: {a.display} -> {a.team}{' (captain)' if a.captain else ''}")


def list_all(_a):
    teams = db.query_all("SELECT * FROM lan_teams ORDER BY COALESCE(seed, 999), name")
    if not teams:
        print("(no teams)")
        return
    for t in teams:
        print(f"[{t['id']}] {t['name']} ({t['tag'] or '-'})  seed={t['seed']}")
        roster = db.query_all(
            "SELECT * FROM lan_players WHERE team_id=%s ORDER BY is_captain DESC, display_name",
            (t["id"],),
        )
        for p in roster:
            cap = " *captain*" if p["is_captain"] else ""
            print(f"     - {p['display_name']}  discord={p['discord_id']}  steam={p['steam_id']}{cap}")


def main():
    ap = argparse.ArgumentParser(description="WSDoD LAN 2026 Phase-0 admin CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add-team")
    p.add_argument("--name", required=True)
    p.add_argument("--tag", default=None)
    p.set_defaults(fn=add_team)

    p = sub.add_parser("add-player")
    p.add_argument("--team", required=True)
    p.add_argument("--display", required=True)
    p.add_argument("--discord", type=int, default=None)
    p.add_argument("--discord-name", dest="discord_name", default=None)
    p.add_argument("--steam", default=None)
    p.add_argument("--captain", action="store_true")
    p.set_defaults(fn=add_player)

    p = sub.add_parser("list")
    p.set_defaults(fn=list_all)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
