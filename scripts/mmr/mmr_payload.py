"""Translate the ladder's output into the `mmr_openskill` season aggregate.

The gap this closes
-------------------
run_weekly writes {player_id: {mu, sigma, ordinal}}. keep-the-prac's profile
card (PR #760) reads a `ktp.season_aggregate` row of kind `mmr_openskill`
holding rows keyed by ALIAS with `matches`, `rating`, `uncertainty` and
`conservative`. Nothing bridged the two, so the card renders nothing on every
profile -- by design, but permanently until this exists.

`conservative` is mu - 3*sigma, confirmed against the consumer's own test
fixture (rating 26.4, uncertainty 8.22, conservative 1.74). That is the same
ordinal the ladder already computes, so the two sides agree by construction
rather than by coincidence.

What this module does NOT do
---------------------------
Write anything. It builds a payload; `report_service.py import-mmr` is what
inserts it, and only that runs where the data server's write credential
lives. Keeping the translation pure means it is testable here, in CI, without
any credential at all -- and it means the operator step is a single command
over a file rather than a script that recomputes ratings on a box that has no
business recomputing them.

Privacy note: the payload carries aliases, never player ids or Steam ids,
matching every other public surface. A player with no alias is dropped rather
than published under an id.
"""
from __future__ import annotations

import re

AGGREGATE_KIND = "mmr_openskill"
METHOD_VERSION = "openskill_pl_v1"
# Below this, a rating is too thinly evidenced to show a player as fact. The
# consumer reads this from the payload rather than hard-coding it, so the
# threshold can move without a website deploy.
MIN_MATCHES_FOR_DISPLAY = 3

# A rating is shown only once its uncertainty has actually come DOWN, not
# merely once the player has appeared N times. The convention is half the
# model's starting sigma -- the usual "converged" line for a Bayesian skill
# rating, and the point at which mu - 3*sigma stops being dominated by sigma.
#
# Expressed as a fraction of the model's own starting sigma rather than an
# absolute, so it tracks the model instead of silently becoming wrong if beta
# or the starting sigma ever change.
#
# WHY A SIGMA GATE AT ALL. Matches-played was the wrong proxy. On 2026-09-29
# every displayable player had exactly 3 matches and an identical sigma of
# 8.16, barely off the 8.333 starting value -- so `conservative` (mu - 3*sigma)
# was simply mu - 24.5, and NEGATIVE for 20 of 41. A match count says how often
# someone turned up; sigma says whether the rating knows anything yet, and that
# is the question the card is actually asking.
SIGMA_CONVERGED_FRACTION = 0.5

# PlackettLuce's starting sigma (25/3). Written as a LITERAL rather than read
# from `ladder`, because report_service.py imports this module on the data
# server and `ladder` drags in openskill, which is not installed there -- the
# exact breakage #559 had to fix. `test_start_sigma_matches_the_ladder` pins
# this against the real model so the duplication cannot drift silently.
MODEL_START_SIGMA = 25.0 / 3.0
MAX_SIGMA_FOR_DISPLAY = MODEL_START_SIGMA * SIGMA_CONVERGED_FRACTION


def conservative(mu, sigma):
    """mu - 3*sigma: the value the consumer ranks and displays.

    Deliberately pessimistic. A player two matches in can post a flattering
    mu; publishing that as their skill would be a claim the evidence does not
    support, and it is the player's own profile reading it back at them.
    """
    return round(float(mu) - 3.0 * float(sigma), 2)


def build(ratings, matches_played, aliases, *, generated_at,
          min_matches=MIN_MATCHES_FOR_DISPLAY, max_sigma=None, source_report_count=0,
          report_schema_version=9):
    """Build the aggregate payload.

    ratings: {player_id: {"mu", "sigma", ...}} straight from run_weekly.
    matches_played: {player_id: int} -- how many matches actually rated them.
    aliases: {player_id: alias or None}.

    Rows are sorted by conservative descending so the payload is stable: an
    unordered payload would hash differently run to run and publish a new
    revision every week for no change.
    """
    rows = []
    for pid, rating in ratings.items():
        key = int(pid)
        alias = (aliases.get(key) or "").strip()
        if not alias:
            continue          # never publish someone under a raw id
        mu, sigma = rating.get("mu"), rating.get("sigma")
        if mu is None or sigma is None:
            continue
        rows.append({
            "name": alias,
            "matches": int(matches_played.get(key, 0)),
            "rating": round(float(mu), 2),
            "uncertainty": round(float(sigma), 2),
            "conservative": conservative(mu, sigma),
        })
    rows.sort(key=lambda r: (-r["conservative"], r["name"].lower()))
    # Gate HERE, in the producer, rather than publishing a threshold and
    # trusting the consumer to apply it. That was the previous design and it
    # failed silently: keep-the-prac's findMmrEntry never checked min_matches
    # (its own docstring said it did), so every player in the payload got a
    # card -- 120 of 161 below the threshold, 41 of them on a single match.
    # A row that should not be displayed is a row that should not be published.
    rated = len(rows)
    gate = MAX_SIGMA_FOR_DISPLAY if max_sigma is None else float(max_sigma)
    shown = [r for r in rows
             if r["matches"] >= int(min_matches) and r["uncertainty"] <= gate]
    return {
        "kind": AGGREGATE_KIND,
        "provisional": True,
        "notice": ("Provisional rating: recomputed from the whole season every "
                   "week, so published values change retroactively."),
        "method_version": METHOD_VERSION,
        "generated_at": generated_at,
        "min_matches": int(min_matches),
        "max_uncertainty": round(gate, 3),
        # Everyone the ladder rated, displayable or not. The import guard
        # checks THIS, so "nobody is confident enough yet" stays publishable
        # while "the builder produced nothing" still fails.
        "rated_players": rated,
        "withheld_players": rated - len(shown),
        "players": shown,
        # Carried so the existing aggregate insert path can write this row
        # without a special case.
        "source_report_count": int(source_report_count),
        "report_schema_version": int(report_schema_version),
    }


REQUIRED_ROW_FIELDS = ("name", "matches", "rating", "uncertainty", "conservative")
FORBIDDEN_ROW_FIELDS = ("player_id", "steam_id", "steam_id64", "steamid")
# Compared after lowercasing and dropping separators, so steamId and Player-ID match too.
_FORBIDDEN_KEY_FORMS = frozenset(
    "".join(ch for ch in name if ch.isalnum())
    for name in FORBIDDEN_ROW_FIELDS + ("uniqueid", "steamid2", "steamid3", "steamid32"))
_STEAM_ID = re.compile(r"STEAM_[0-5]:[01]:\d+|\[U:1:\d+\]|7656119\d{10}", re.IGNORECASE)


def _identifier_like_key(key):
    # A digit-only key is an id map (run_weekly keys ratings by player id).
    text = str(key).strip()
    return (text.isdigit() or bool(_STEAM_ID.search(text))
            or "".join(ch for ch in text.lower() if ch.isalnum()) in _FORBIDDEN_KEY_FORMS)


def identifier_problems(payload):
    """Every identifier anywhere in the payload: forbidden or id-shaped KEYS at
    any depth, and SteamID-shaped string values. The importer writes the whole
    document, so a field outside `players` publishes exactly as one inside it."""
    keys, values = set(), set()
    stack = [("", payload)]
    while stack:
        path, node = stack.pop()
        if isinstance(node, dict):
            for key, child in node.items():
                where = f"{path}.{key}" if path else str(key)
                if _identifier_like_key(key):
                    keys.add(path or "<top>")
                stack.append((where, child))
        elif isinstance(node, list):
            stack.extend((f"{path}[]", child) for child in node)
        elif isinstance(node, str) and _STEAM_ID.search(node):
            values.add(path)
    problems = []
    if keys:
        problems.append(
            f"payload carries identifiers as keys under {sorted(keys)}; aliases only")
    if values:
        problems.append(
            f"payload carries SteamID-shaped values at {sorted(values)}; aliases only")
    return problems


def validate_for_import(payload):
    """Problems that should stop this payload being written. [] means fine.

    Lives here rather than in report_service so it is importable, and
    therefore testable, without the data server's Unix-only dependencies --
    the guards on a production write are exactly the code that should not
    ship untested.
    """
    if not isinstance(payload, dict):
        return ["payload is not an object"]
    problems = []
    if payload.get("kind") != AGGREGATE_KIND:
        problems.append(f"kind is {payload.get('kind')!r}, expected {AGGREGATE_KIND!r}")
    # Runs before the shape checks, so a refusal on shape still names a leak.
    problems += identifier_problems(payload)
    rows = payload.get("players")
    if isinstance(rows, dict):
        problems.append(
            "players is an object keyed by player; the consumer reads a list of "
            "alias rows")
        return problems
    if not isinstance(rows, list):
        problems.append("payload carries no players")
        return problems
    # An EMPTY players[] is legitimate and must stay publishable: it is what
    # "the ladder rated people, but none of them are certain enough to show"
    # looks like, which is the honest state early in a season. A broken build
    # is distinguished by having rated nobody at all.
    rated = payload.get("rated_players")
    if rated is None:
        rated = len(rows)                      # payload predating the field
    if not rated:
        problems.append("payload carries no players")
        return problems
    if not rows:
        return problems                        # nothing to check field-wise
    if not all(isinstance(row, dict) for row in rows):
        problems.append("player rows must all be objects")
        return problems
    missing = sorted({f for f in REQUIRED_ROW_FIELDS
                      for row in rows if f not in row})
    if missing:
        problems.append(f"player rows are missing {missing}")
    return problems
