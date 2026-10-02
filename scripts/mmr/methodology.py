"""The `rating_methodology` season aggregate: how KTPR, MMR and momentum are
computed, with every variable and its current value, per map.

Published so the website can show it under Stats -- the equations, the
parameters, the sample each number was fitted on and how well it fit. The
numbers change as data lands (weekly refit), and this document changes with
them, so a reader always sees what the ratings on the site were actually
computed with.

It carries no player rows: nothing here is about anyone. Same publish path
as `mmr_openskill` (CI writes the file, the operator imports it).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # scripts/: ktpr_v2, analytics_report_dto
sys.path.insert(0, str(HERE.parents[1]))      # repo root: analytics_report_dto imports scripts.*

import analytics_report_dto as DTO             # noqa: E402
import ladder                                  # noqa: E402
import mmr_payload as MMRP                     # noqa: E402
import performance as PF                       # noqa: E402
from ktpr_v2 import KtprV2Config               # noqa: E402
# Re-exported, never redefined. They live in a module of their own because the
# import command must reach them without importing this one, which drags the
# OpenSkill solver in through `ladder`.
from methodology_schema import (AGGREGATE_KIND, FORBIDDEN_KEYS,  # noqa: E402,F401
                                METHOD_VERSION, validate_for_import)

PARAMS = HERE / "momentum_params.json"

# Every number below is read from the code that uses it, never retyped, so
# this document cannot say one thing while the ratings do another.
_W = KtprV2Config()
_SCALE = {"center": int(DTO.KTPR_DISPLAY_CENTER), "scale": int(DTO.KTPR_DISPLAY_PER_Z), "floor": int(DTO.KTPR_DISPLAY_FLOOR)}
_INIT = ladder.OpenSkill().m.rating()

KTPR_V2 = {
    "name": "KTPR v2",
    "what": "Per-match performance rating. How well you played in this match, independent of who won.",
    "equation": "z = Σ w_c · z_c over the components available for the match; "
                "each z_c is the player's per-match z-score on that component "
                "(mean 0, spread 1 across the players in the match). "
                "A missing component's weight is redistributed over the rest.",
    "components": [
        {"name": "swing", "weight": _W.swing_weight,
         "what": "attributed flag swing: the flag-control probability your kills and caps moved"},
        {"name": "kast_f", "weight": _W.kast_weight,
         "what": "KAST-F: share of your lives with a kill, assist, survival or trade in a flag fight"},
        {"name": "output", "weight": _W.output_weight, "what": "damage per life / 100 + kill/death ratio"},
        {"name": "multikill", "weight": _W.multikill_weight, "what": "fast 2k + 2·fast 3k + 4·fast 4k+"},
    ],
    "display": {"equation": f"max({_SCALE['floor']}, {_SCALE['center']} + {_SCALE['scale']}·z)",
                "center": _SCALE["center"], "scale": _SCALE["scale"], "floor": _SCALE["floor"],
                "what": f"{_SCALE['center']} is the match average; {_SCALE['center'] + _SCALE['scale']} is one spread above it"},
    "status": "provisional",
}

MMR = {
    "name": "MMR (OpenSkill)",
    "what": "Cross-match skill rating. How likely your side is to win, learned from results across the season. "
            "Carries an uncertainty that shrinks with matches played.",
    "model": "Plackett-Luce (openskill 6.2.0), two teams, each player's rating updated by the match result",
    "initial": {"mu": round(_INIT.mu, 3), "sigma": round(_INIT.sigma, 3),
                "what": "everyone starts here; sigma is the uncertainty"},
    "displayed": {"rating": "mu", "uncertainty": "sigma", "conservative": "mu − 3·sigma",
                  "what": "conservative is the value you are very likely at least as good as"},
    "min_matches": MMRP.MIN_MATCHES_FOR_DISPLAY,
    "prediction": {
        "equation": "p_damped = 0.5 + (p − 0.5) · n / (n + k)",
        "k": ladder.EVIDENCE_K,
        "n": "the thinner side's mean matches played",
        "what": "a prediction between two barely-rated sides is pulled toward a coin flip; "
                "confidence is earned by evidence, not asserted by the model",
    },
    "performance_weighting": {
        "enabled": False, "strength": PF.DEFAULT_STRENGTH,
        "what": "when on, a side's rating change is split by each player's KTPR contribution "
                "instead of evenly. Off until measured to predict better than even splits.",
    },
    "status": "provisional",
}

MOMENTUM = {
    "name": "Momentum credit",
    "what": "Objective value traced back to the plays that enabled it. A 4k that leads to a cap "
            "and then a capout is paid part of that objective value, decaying with the lag.",
    "mechanism": [
        "Every momentum event (multikill, cap, capout) is both a payout and a deposit for its team's ledger.",
        "Payout: the event's value is split between the actor(s) and the team's outstanding deposits; "
        "the deposits' share at lag d is 1 − 1/lift(d).",
        "Deposit: the event enters the ledger and forwards a fraction rho of anything it is later paid "
        "to the deposits that fed it — the secondary assist.",
        "An enemy cap clears the ledger.",
        "Kills earn nothing here; KTPR already counts them. This is objective lift only.",
    ],
    "status": "research — not yet a KTPR component",
}


# S10's first match week. A run's week number is derived from its own
# timestamp, so a re-run of an old week lands on that week, not on today's.
SEASON_START = date(2026, 9, 13)


def as_date(value):
    """The date in a run's `generated_at`, or None if there isn't one.

    `weekly_summary.json` carries a DISPLAY timestamp, not ISO 8601 --
    run_weekly writes `strftime("%Y-%m-%d %H:%M UTC")`, e.g.
    "2026-09-21 18:57 UTC". Parsing only ISO here is what made the first cut of
    this feature emit an empty history against every real summary while the
    tests, which used invented ISO strings, passed. Both shapes are accepted,
    and `test_the_production_timestamp_format_parses` pins the real one.
    """
    s = str(value or "").strip()
    if not s:
        return None
    s = re.sub(r"\s+(UTC|GMT|Z)$", "", s)
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def week_of(generated_at):
    """Season week number for a run's `generated_at`, or None if unreadable."""
    d = as_date(generated_at)
    if d is None:
        return None
    days = (d - SEASON_START).days
    return (days // 7) + 1 if days >= 0 else None


def week_entry(summary):
    """One `version_history` row from a `weekly_summary.json` dict.

    None when the summary carries no usable timestamp, or no rated matches --
    a week with nothing rated has no accuracy to report and must not land as
    a 0% row the reader would read as a regression.
    """
    if not isinstance(summary, dict):
        return None
    week = week_of(summary.get("generated_at"))
    matches = summary.get("completed_matches") or 0
    if week is None or not matches:
        return None
    upsets = summary.get("upsets") or 0
    return {
        "week": week,
        "date": as_date(summary["generated_at"]).isoformat(),
        "accuracy_pct": round((summary.get("accuracy") or 0) * 100, 1),
        "log_loss": summary.get("log_loss"),
        "completed_matches": matches,
        "upsets": upsets,
        "upsets_pct": round(upsets / matches * 100, 1),
        "headline": summary.get("headline", ""),
    }


def merge_history(prior, entry):
    """`prior` history with `entry` folded in: one row per week, oldest first.

    A re-run of a week REPLACES that week's row rather than appending a second:
    every value is refit on the whole corpus each run, so the newer row is the
    truth about that week and two rows for one week would read as progression.
    """
    by_week = {}
    for row in prior or []:
        if isinstance(row, dict) and row.get("week") is not None:
            by_week[row["week"]] = row
    if entry:
        by_week[entry["week"]] = entry
    return [by_week[w] for w in sorted(by_week)]


def build(params, *, generated_at, source_report_count=0, report_schema_version=9,
          summary=None, prior_history=None, division_seed=None):
    """The payload. `params` is momentum_params.json as a dict.

    `summary` is this run's `weekly_summary.json` as a dict, and `prior_history`
    the `version_history` of the previous published payload. Both are passed in
    rather than read from disk: on a CI runner the checkout is fresh, so a file
    read here would find nothing and the history would silently stay empty.
    """
    maps = {}
    for mp, m in sorted(params.get("maps", {}).items()):
        maps[mp] = {
            "sample": {k: m[k] for k in ("halves", "official_halves", "multikills", "caps", "capouts")},
            "momentum_curves": m["curves"] if m.get("curves") else {"uses": "pooled"},
            "scoring": m["scoring"] if m.get("scoring") else {"uses": "fallback",
                                                                "fallback": params["definitions"]["fallback"]["scoring"]},
        }

    return {
        "kind": AGGREGATE_KIND,
        "method_version": METHOD_VERSION,
        "generated_at": generated_at,
        "provisional": True,
        "notice": "All values are refit as matches land and may change week to week. "
                  "Sample sizes and fit quality are shown so the reader can judge each number.",
        "ktpr_v2": KTPR_V2,
        "mmr": {**MMR, "division_seeding": _division_seeding(division_seed)},
        "momentum": {
            **MOMENTUM,
            "definitions": params.get("definitions", {}),
            "fitted_at": params.get("generated_at"),
            "corpus": params.get("corpus", {}),
            "rho": params.get("rho", {}),
            "pooled_curves": params.get("pooled", {}),
            "maps": maps,
        },
        "version_history": merge_history(prior_history, week_entry(summary)),
        "source_report_count": int(source_report_count),
        "report_schema_version": int(report_schema_version),
    }


def _division_seeding(seed):
    """How the published ratings describe their own division prior.

    This has to be on the page, and it has to be honest, because seeding
    changes what the number MEANS: league divisions never play each other, so
    without a prior their rating pools are ordered only by chance -- and WITH
    one, a rating is partly an echo of the division it was seeded from. A
    reader comparing a bottom-gold player against a mid-silver player is
    entitled to know which of those two situations they are looking at.
    """
    seed = seed or {}
    enabled = bool(seed.get("enabled"))
    return {
        "enabled": enabled,
        "offsets_mu": seed.get("offsets") or {},
        "labelled_players": seed.get("labelled_players") or 0,
        "what": ("Starting rating is offset by the player's division, because divisions "
                 "do not play each other and so their rating pools cannot otherwise be "
                 "compared. The offset is measured on 12-mans, which do mix divisions."
                 if enabled else
                 "Starting rating is the same for every player regardless of division. "
                 "Divisions do not play each other, so ratings from different divisions "
                 "are NOT on a common scale and should not be compared directly."),
        "status": ("prior, not a measurement of this player -- it is an assumption about "
                   "their division that a handful of results will override"
                   if enabled else "no division prior applied"),
        "caveat": ("Because the prior comes from division, these ratings cannot be used as "
                   "independent evidence for promotion or relegation -- that would be "
                   "circular. Re-run with --no-division-seed for that comparison."
                   if enabled else None),
    }


def load_params(path=PARAMS):
    return json.loads(Path(path).read_text(encoding="utf-8"))


PAYLOAD = HERE / "rating_methodology_payload.json"


def weeks_lost(new_history, prior_history):
    """Weeks in `prior_history` that `new_history` has dropped.

    The history only ever grows: a week already published is a fact about the
    season, and the only reason to emit fewer is that something upstream lost
    them. The restore step cannot tell a transient clone failure from "the
    branch does not exist yet" -- both leave it with no prior payload -- so
    without this the publish would overwrite the season's earlier weeks in
    silence. Compared as SETS, not lengths: losing week 1 while gaining week 3
    keeps the count and is still a loss.
    """
    def ws(h):
        return {r["week"] for r in (h or [])
                if isinstance(r, dict) and r.get("week") is not None}
    return sorted(ws(prior_history) - ws(new_history))


def load_prior_history(path=PAYLOAD):
    """`version_history` from a previously published payload; [] if there is none.

    The previous payload is the only place a past week survives: every run
    starts from a fresh checkout, and the season's weeks live on the
    `mmr-ratings` branch, not in the repo. The weekly workflow restores that
    file into the workspace before the run so this finds it.
    """
    try:
        prior = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    history = prior.get("version_history") if isinstance(prior, dict) else None
    return history if isinstance(history, list) else []


if __name__ == "__main__":
    # The weekly workflow's publish guard, run from the data branch's checkout:
    #   python methodology.py <payload about to publish> <payload already there>
    # Exits non-zero, with the annotation the job surfaces, if publishing would
    # drop a week the branch already carries.
    _new, _old = (load_prior_history(p) for p in sys.argv[1:3])
    _lost = weeks_lost(_new, _old)
    if _lost:
        raise SystemExit(
            f"::error::refusing to publish: the methodology history would lose "
            f"week(s) {_lost} (publishing {len(_new)}, the branch has {len(_old)}). "
            f"The restore step most likely failed -- re-run the job rather than "
            f"overwriting the season's history.")
    print(f"history check: publishing {len(_new)} week(s), none lost")
