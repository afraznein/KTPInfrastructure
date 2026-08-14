# Per-match pages — spec

Drafted 2026-08-14. Not built. Depends on the awards framework landing first.

## Shape

Static shell, fetched data. `build_site.py` gains a pass emitting
`dist/match/<slug>/index.html` per match; the scoreboard and the award strip are
fetched at load. That split is deliberate — the shell has no gated content, and
everything that *is* gated arrives through an endpoint that can refuse it.

Serving needs no change: the app already mounts `dist/` at `/`, and nested
directories already work (`dist/2025/`, `dist/next/`).

## URLs

`/match/sun-railroad2-nato-vs-icyhot/`

Slug is `<day>-<map>-<teamA>-vs-<teamB>`, clubs lowercased to their tag, map
stripped of its `_b3e`/`_s9a` suffix. Collisions take a `-2` suffix.

⚠️ **Slugs must be frozen on first generation, in a committed
`match-slugs.json`.** Regenerating them is how a shared Discord link dies. New
matches get appended; existing entries are never recomputed, even if the team
name they were built from later changes.

The raw match key (`1785715972-KTP1`) gets a redirect route to its slug, so
anything already referencing a key keeps working.

## Which matches get a page

⚠️ **Resolve this first — three different counts are in play, and they answer
different questions:**

- `hud_events` `ktp_match_end` rows for the tournament window — the set
  `apply_award_decisions.py` scopes to.
- `match-teams.json` — the curated tournament set, which additionally holds
  `1785715972-KTP1`: real play whose logging died before the match could close.
- The Results section's own header, which states a third number.

`apply_award_decisions.py` already documents the first two as "not the same
question". The third is unattributed prose and is the least trustworthy.

✅ **DECIDED 2026-08-14: the curated set (`match-teams.json`) gets the pages** — a
match that was played deserves one even if its logging died before it could
close. The Results header is reconciled to that set, not the reverse. A page
whose match has no closing event renders its scoreboard from what does exist and
says so, rather than being omitted.

## Gate decision

✅ **DECIDED 2026-08-14.** New surfaces are API-native; the legacy board gets a
route that can strip its data block.

These pages fetch their scoreboard from `GET /api/stats/match/{key}` from the
first commit — no baked stats, so `stats_published` gates them natively. That
matters most here: per-match pages are where baked scoreboards would multiply
across the whole tournament rather than sitting in one file.

The existing single-page stats board keeps its embedded `#lan-data` block, and
an explicit route in front of the `Mount("/")` omits that block when
`stats_published` is 0. Chosen over converting `buildStatsBoard` to async
because that renderer — three view tabs, position/team/map chips, sortable
columns, detail expanders — works today, and the gate is currently dormant.
⚠️ A strip that silently fails to match fails **open**, so the test asserting
the payload is absent from the served bytes is the load-bearing part, not the
strip itself.

## Page contents

**Baked (no gate — all of it is already public in the Results section):**
teams, map, day, round, final score, half-by-half score, veto sequence, demo
link, match notes.

**Fetched from `GET /api/stats/match/{key}` (gated on `stats_published`):**
the per-player scoreboard — kills, deaths, K/D, headshots, flags, damage,
assists, best streak, per half and match total. Reuses the stats board's
existing column and sort machinery.

**Fetched from `GET /api/awards/candidates?edition=&match=<key>`:** that match's
own records. Already supported by the awards API; staff get the same greyed
cards and checkboxes they get on the awards page.

When `stats_published` is 0 the scoreboard endpoint returns no rows and the page
says results are not published yet — it must not render an empty table, which
reads as "nobody scored".

## Per-page metadata

Each page carries its own `<title>` and OpenGraph tags — *"NATO vs icyHOT ·
railroad2 · WSDoD Philly 2026"*. This is the concrete advantage over a
query-string view (`?m=<key>`): a match link pasted into Discord unfurls as that
match rather than as the site's front page.

## Discovery

The Results section's match log rows link to their page. That is the only entry
point needed; the pages do not go in the nav.

## Data sources

*(Corrected 2026-08-14: this section listed the stats tables as the endpoint's
sources. They are the GENERATOR's. lan-web connects as `ktp_lan` and has no
privilege on `hlstatsx_lan` — the same wall that left `lan_stats_publication`
unreadable by the app meant to read it.)*

**The generator** reads `hlstatsx_lan` over SSH: `match-teams.json` (clubs),
`captures-placed.json` (match → map), `ktp_match_stats` + `ktp_match_players`
(per player per half — halves 1 and 2 only, half 0 is the match total and would
double everything), `hud_player_stats` (assists), the frag log (streaks),
`veto.json`, the demo URLs, `match-notes`.

**The endpoint** reads `lan_matches` + `lan_match_scoreboard` in `ktp_lan`,
which the generator populates. Same shape as the awards pipeline: build reads
the stats database, writes lan-web's.

⚠️ **Not a JSON emitted into the site tree.** Anything the build writes under
`site_dir` is served byte-for-byte by the `StaticFiles` mount — an ungated
second door onto precisely the dataset `stats_published` exists to withhold.

## `GET /api/stats/match/{key}` — the response, frozen

*(Added 2026-08-14 after the page and the endpoint were built against different
assumed shapes. The page read `row.name` / `row.kills`; the endpoint returns
`who` and a nested `total`. Nothing errored — `published` was true and
`players.length` was non-zero, so the honesty guard passed and it rendered a
full table of em-dashes, which looks like data and is worse than an empty
state. A prose description was not enough; this is the contract.)*

```json
{
  "published": true,
  "is_staff": false,
  "match": {
    "key": "1785604799-KTP3",
    "edition": "philly-2026",
    "day": "08-01",
    "map": "armory_b6",
    "teams": ["Best Buds", "North Atlantic Treaty Org"],
    "halves": [1, 2],
    "closed": true
  },
  "players": [
    {
      "steam_id": "1:2052836",
      "who": "piff",
      "team": "Best Buds",
      "total":  {"kills": 60, "deaths": 51, "headshots": 11, "damage": 8904,
                 "flags": 8, "assists": 11, "best_streak": 5, "kd": 1.176},
      "halves": [{"half": 1, "kills": 31, "deaths": 27, "...": "..."},
                 {"half": 2, "kills": 29, "deaths": 24, "...": "..."}]
    }
  ],
  "sources": {}
}
```

- The player's display name is **`who`**, matching the award cards — not `name`.
- Stats live under **`total`** and per-half in `halves`; they are never on the
  player object itself.
- `halves` on the match header is which halves exist. An abandoned match has
  `[1]`, so the page must not assume two.
- `closed: false` means the match was played but its logging died. It still has
  a board, and it still gets a page.
- Unpublished-and-not-staff returns `{"published": false, "match": null,
  "players": []}`. An unknown key is **404**, which is a different answer from a
  known match with no rows.

## Placing a capture in a half — the one derivation the schema cannot give you

⚠️ **`hlstats_Events_PlayerActions` has no `half` column.** It carries only
`eventTime`, so "flags per half" cannot be read off it directly and a naive
join invents one.

Each capture is placed inside that half's own `[start_time, end_time]` window
from `ktp_matches`, which holds one row per `(match_id, half)`. Every capture in
the tournament set lands in exactly one half, none double-counted, and
`build_match_scoreboard.py` refuses to write if that ever stops being true —
the guard is the point, since a capture falling outside both windows would
otherwise vanish silently.

## Build cost

The shells are small because the data is fetched. Assets are shared from
`../../assets/`, already emitted once by `build_site.py`.

## Not in scope

Per-match award *types* — the awards page shows the best single match of the
weekend, one card per award. These pages show the same award types scoped to one
match, which the API already does with `?match=`. No new award definitions.
