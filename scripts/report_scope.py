"""Which matches the report pipeline treats as in season.

One definition for generate, aggregate and report_sync, so the three steps
cannot disagree about what reaches the website.
"""
from __future__ import annotations

# KTPMatchHandler's own predicate, mirrored: is_official_match_type(t) is
# t == MATCH_TYPE_COMPETITIVE (0, .ktp) or t == MATCH_TYPE_KTP_OT (4, .ktpOT)
# — the two password-gated, results-bearing types. Spelling that set out
# per-site is how .ktpOT ended up cancellable while .ktp was protected.
OFFICIAL_MATCH_TYPES = (0, 4)

# The demo filename's leading label -> the same ids, because the HLTV recorder
# names files by match type and nothing else binds the two. Mirrored from
# KTPMatchHandler's MatchType enum: COMPETITIVE 0, SCRIM 1, 12MAN 2, DRAFT 3,
# KTP_OT 4, DRAFT_OT 5. The overtime types are absent on purpose -- no demo
# directory for them exists in the corpus, so their label is unknown and a
# caller must raise rather than guess which id an unlabelled type carries.
MATCH_TYPE_BY_DEMO_LABEL = {"ktp": 0, "scrim": 1, "12man": 2, "draft": 3}

# Types a report is BUILT for but never published: a shadow report exists so
# analytics can see the play, not so the site can show it. 2 is 12man (drew,
# 2026-09-23). Scrims (1) deliberately stay out — the hidden-value review
# already discounts scrim play as loose, so building them buys nothing.
#
# Nothing downstream needs a second gate for this: classify() returns
# HELD_BY_TYPE for a match with no official-type half, so aggregate and
# report_sync hold a shadow report back on the rule they already apply to a
# report written by an explicit --match-ids run.
SHADOW_MATCH_TYPES = (2,)

# What generate DISCOVERS. Publication scope stays OFFICIAL_MATCH_TYPES.
DISCOVERED_MATCH_TYPES = OFFICIAL_MATCH_TYPES + SHADOW_MATCH_TYPES

IN_SCOPE = "in"
HELD_BY_SINCE = "since"
HELD_BY_TYPE = "match_type"
# No row in ktp.match_game_link: the website's roster-overlap correlation
# could not bind this game match to a scheduled fixture.
#
# This exists because match_type alone is structurally racy. generate() reads
# whatever match_type says at cron-tick time; an admin who types `.ktp` by
# mistake and corrects it minutes later has already had the report published,
# and report_sync only ever inserts, so Supabase never un-publishes. That is
# not hypothetical -- 1790186507-NY1 reached the site exactly that way on
# 2026-09-23. A fixture link cannot be produced by a mistyped command.
HELD_NO_FIXTURE = "fixture_link"


def match_scope_columns(alias: str) -> str:
    """`match_start` (latest half of any type) and `official_start` (latest
    official-type half) for the match_id column of `alias`.

    IN drops a NULL match_type the way generate's discovery filter does, and
    the type is never read into Python, so match_type 0 cannot be mistaken
    for "no type" by a truthiness test.
    """
    types = ", ".join(str(t) for t in OFFICIAL_MATCH_TYPES)
    same = f"BINARY m.match_id = BINARY {alias}.match_id"
    return (
        f"(SELECT MAX(m.start_time) FROM ktp_matches m WHERE {same}) "
        "AS match_start, "
        f"(SELECT MAX(m.start_time) FROM ktp_matches m WHERE {same} "
        f"AND m.match_type IN ({types})) AS official_start"
    )


def _absent(value: str) -> bool:
    return value in ("", "NULL")


def classify(match_start: str, official_start: str, since: str) -> str:
    """IN_SCOPE only when an official-type half started on or after `since`:
    the same per-half test generate discovers matches by."""
    # No ktp_matches row at all: the date cannot be proved.
    if _absent(match_start):
        return HELD_BY_SINCE
    if _absent(official_start):
        return HELD_BY_TYPE
    return IN_SCOPE if official_start >= since else HELD_BY_SINCE


def print_held(held: dict[str, int], since: str) -> None:
    if held.get(HELD_BY_SINCE):
        print(f"held back by --since {since}: "
              f"{held[HELD_BY_SINCE]} publishable report(s)")
    if held.get(HELD_BY_TYPE):
        types = ", ".join(str(t) for t in OFFICIAL_MATCH_TYPES)
        print(f"held back by match_type (official only: {types}): "
              f"{held[HELD_BY_TYPE]} publishable report(s)")


def print_unlinked(match_ids: list[str], enforcing: bool) -> None:
    """Name every match with no fixture link, one per line.

    Named, not counted. The dangerous case for this gate is the inverse of the
    bug it fixes: if the website's correlation sweep stops running, real
    matches stop linking and this withholds reports that should publish. That
    failure is recoverable -- a late report, never a wrong one -- but only if
    somebody can see it, and a bare count in a nightly log is not seeing it.
    """
    if not match_ids:
        return
    verb = "held back" if enforcing else "WOULD be held back"
    print(f"{verb}, no ktp.match_game_link fixture binding: "
          f"{len(match_ids)} publishable report(s)")
    for match_id in sorted(match_ids):
        print(f"  {match_id}: no scheduled fixture correlates to it")
    if not enforcing:
        print("  (--require-fixture-link is off; these still published)")
