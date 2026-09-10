"""One-shot pull of the ktp schema tables this workstream needs, from the
keep-the-prac Supabase project. Read-only REST, no schema/write access.

Requires the publishable (anon) key -- see handover/MMR_WEBSITE_DATA_ACCESS_
20260906.md in keep-the-prac. Pass it as --key or set
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY in the environment.

Every table here has a confirmed public SELECT policy (see SCHEMA.md /
migrations in keep-the-prac) -- this script does not touch anything else.
Not run yet: no key available as of 2026-09-07. Written against the
confirmed schema so this is a one-command job the moment the key exists.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_URL = "https://yxpjfenpnwksvvquqlde.supabase.co"
SCHEMA = "ktp"
OUT = Path(__file__).parent / "data" / "website"

# table -> (columns to select, order_by) -- kept minimal and explicit rather
# than select=* so a schema change breaks loudly here instead of silently
# changing what downstream code receives.
TABLES = {
    "legacy_match": ("season_id,team_a,team_b,division,playoff_division,stage,"
                      "score_unit,score_a,score_b,forfeit,week,played_on,map,note", "played_on"),
    "legacy_season_team": ("id,season_id,name,tag,division,wins,losses,point_diff,place,"
                            "place_of,champion,playoff_seed,playoff_place", "season_id"),
    "legacy_player_season": ("player_id,season_id,legacy_season_team_id,steam_id64,"
                              "unattributed_label,note", "season_id"),
    "legacy_match_game": ("legacy_match_id,game_match_id,map_name,started_at,method,"
                           "confidence,complete", "started_at"),
    "player_steam": ("player_id,steam_id64,status,valid_from,valid_to", "player_id"),
    "team": ("id,name,slug,tag", "id"),
    "season": ("id,slug,number,term,year,name,starts_on,ended_on,is_legacy,state", "number"),
    "division": ("id,season_id,name,slug,tier_order", "season_id"),
    "season_team": ("id,season_id,team_id,division_id,seed,status", "season_id"),
    "season_team_member": ("season_team_id,player_id,joined_at,left_at,source", "season_team_id"),
}

PAGE_SIZE = 1000


def fetch_table(key: str, table: str, select: str, order_by: str) -> list[dict]:
    rows, offset = [], 0
    while True:
        url = (f"{PROJECT_URL}/rest/v1/{table}?select={select}"
               f"&order={order_by}&limit={PAGE_SIZE}&offset={offset}")
        req = urllib.request.Request(url, headers={
            "apikey": key, "Authorization": f"Bearer {key}",
            "Accept-Profile": SCHEMA, "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                page = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"{table}: HTTP {e.code} -- {body[:500]}") from e
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"))
    ap.add_argument("--tables", nargs="*", default=list(TABLES))
    args = ap.parse_args()
    if not args.key:
        sys.exit("No key. Pass --key or set NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY. "
                 "See handover/MMR_WEBSITE_DATA_ACCESS_20260906.md in keep-the-prac.")

    OUT.mkdir(parents=True, exist_ok=True)
    for table in args.tables:
        select, order_by = TABLES[table]
        rows = fetch_table(args.key, table, select, order_by)
        (OUT / f"{table}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"{table}: {len(rows)} rows -> data/website/{table}.json")


if __name__ == "__main__":
    main()
