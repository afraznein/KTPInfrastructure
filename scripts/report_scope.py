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

IN_SCOPE = "in"
HELD_BY_SINCE = "since"
HELD_BY_TYPE = "match_type"


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
