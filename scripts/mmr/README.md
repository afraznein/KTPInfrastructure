# MMR / rating ladder

Per-player skill rating for KTP, and the weekly job that keeps it current.

This is **not** KTPR. KTPR v2 is a per-match performance rating (how well did
you play in this match), computed by `../ktpr_v2.py` and shipped to the
website by the report pipeline. This is a season-spanning **skill** rating
(how likely is your side to win), used for match prediction, division
seeding evidence, and sandbagging screening. The two are complementary and
deliberately separate.

## The weekly job

`run_weekly.py` is the whole loop:

1. Pull completed league matches, rosters and divisions from the website
   (`ktp.match`, `season_team_member`, `division`).
2. For each match, compute each side's strength from its players' current
   ratings and predict the winner **before** looking at the result.
3. Compare against what actually happened; update every player's rating.
4. Report running accuracy / log-loss / Brier / calibration, the week's
   calls vs results, confident misses, and a champion-vs-challenger tuning
   check on held-out matches.

```bash
pip install -r requirements.txt
python run_weekly.py --key sb_publishable_...   # or set NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
```

Needs only the website's publishable key, which is public by design (it is
inlined in the shipped site bundle). **No game-server credentials.** That is
what lets `.github/workflows/mmr-weekly.yml` run this on a hosted runner.

Outputs `ratings_current.json`, `weekly_digest.md`, `weekly_summary.json`.
The workflow commits those and opens an issue when there is a finding.

## Rules this code follows

- **Chronological only.** Never shuffle matches; ratings leak backwards if
  you do. Every evaluation is a walk-forward backtest.
- **Nothing auto-adopts.** A challenger that beats the champion is reported
  for review, never silently applied. Adjustments are accepted only when
  they improve held-out log-loss/calibration.
- **Full deterministic replay** each run rather than incremental state, so a
  bad week cannot silently corrupt stored ratings.
- **Winner labels come from reported scores only**, never inferred from
  captures or kills.

## Files

| File | What it does |
|---|---|
| `run_weekly.py` | The weekly update loop (above). Entry point. |
| `ladder.py` | Elo + OpenSkill models, metrics, backtest harness. The harness is the durable part; models are disposable. |
| `division_history.py` | Bridges website player ids to hlstatsx player ids via Steam ID; builds per-player division history across all seasons. |
| `sandbagging_v2.py` | Screening list: a real division drop **plus** a stat-outlier jump in the lower division. |
| `sandbagging_s9.py` | Earlier pass, kills-per-match z-score within division. Feeds v2. |
| `sandbagging_delta.py` | The delta-flag mechanism (before/after z-scores across a division move), with self-checks. |
| `s10_seeding_validation.py` | Seeds a season from prior-season ratings and compares against admins' real placement. |
| `phase3_lite.py` | Upset dossiers for confidently-wrong predictions. |
| `legacy_ladder.py` | Tested blending S1-S8 legacy results into the ladder. **Rejected** (made prediction worse); kept as the record of what was tried and why. |
| `season_boundary_rehearsal.py` | Season-boundary uncertainty widening, tested across real season boundaries. |
| `identity_merges_from_ac.py` | Builds `data/identity_merges.json` from the anti-cheat identity system (one person, two Steam accounts). |
| `prep_scrim12man.py` | Scrim/12man exposure graph and KTPR warm-start extraction. |
| `pull_website.py` | One-shot pull of the website tables this work needs. |

## Data

`data/` holds only `identity_merges.json` (hlstatsx player-id pairs, no
Steam IDs, no names). Everything else the scripts read — pulled website
tables, S9 corpus exports, the Steam bridge — is derived, may carry
identifiers, and is gitignored. Regenerate with `pull_website.py` and the
queries documented in the research notes.

When the Steam bridge file is absent (as in CI), `run_weekly.py` keys ratings
on the website's own player ids instead, so no Steam identifiers are ever
needed in the repo.

## Momentum credit (research, 2026-09-19)

`momentum.py` is a deposit/payout ledger over a half's multikills, caps and
capouts: every momentum event pays out to the team's outstanding deposits
(attributable share from a fitted lag-lift curve, one curve per objective
kind) and deposits itself, forwarding a fitted fraction `rho` of later
payouts upstream — the hockey secondary assist, so a 4k → cap → capout
chain traces back to the 4k. An enemy cap clears the ledger. Kills earn
nothing here (KTPR has them); this is objective lift only, so it can be
added to the KTPR components without double counting.

```bash
python momentum_fetch.py     # ssh read of officials + 12mans with flag events -> data/events/*.tsv
python momentum_report.py --labels <#434 backfill sql>   # fit curves + per-map scoring, run the ledger -> momentum_report.md
```

Objectives are priced in scoreboard points: a cap owns the flag hold it
started until the next ownership change, and `fit_scoring` fits
`points = cap·caps + hold3·s + hold4·s + capout·capouts` per map on the
demo-labelled halves (thunder: hold time is most of the score, three flags
are worth ~nothing, a capout ~18 on top of its cap). A map without enough
labelled halves pays 1 per cap and 1 per capout until it has them.

Nothing is hand-picked: `lag_lift` measures P(objective within d of a
multikill) against the same team's own rate in that half, `fit_lift` fits
`1 + A·exp(−λd)`, `conditional_lift` gives `rho`. Not yet a KTPR component;
rerun weekly and compare the officials-only tables with the 12man fit as
the season fills in (thunder rarely capouts; lennon/harrington do).

Each map plays differently, so every value is per map: `curves_by_map` fits
the lift curves for any map with ≥150 multikills (pooled fallback below
that) and the scoring fit is per map. `momentum_report.py` writes
`momentum_params.json` — the current values, sample sizes and fit quality
per map — which is versioned and refit weekly as matches land.

## Known weakness: `min_halves`

The only gate on a per-map scoring fit is `fit_scoring_by_map(..., min_halves=12)`
in `momentum_report.py`. A fit with 12 labelled halves that trips no guard can
still be badly ill-conditioned. Bootstrap on `dod_thunder2` (4000 draws at
n=12 halves, error as map-total scoreboard points):

- Draws where a guard fired: median error 18.7%, max 56.4%. Bad, but bounded
  and detectable.
- Draws where no guard fired: median 0.00%, but p99 34.6% and max 1304%. The
  worst one fit `hold3 = -6.67` and `hold4 = +25.8` against true values of
  0.05 and 0.30, pricing `hold4` 86x too high from ill-conditioning alone.

The `max(0.0, ...)` clamp in `value()` hides a negative coefficient but does
nothing about an inflated one, so the output of a bad fit looks sane.
Degeneracy is 0% by n=60 and the wild-coefficient tail is also a small-sample
effect.

Hardening `_solve` would only address the visible half. The lever is the gate.
Two candidates:

1. Raise `min_halves`.
2. Reject a fit on its condition number instead of on a pivot.

These per-map values are published weekly in the `rating_methodology`
aggregate (since e46cff9), so an unflagged wild fit would be displayed on the
site. Which fix to take, or whether to take either, is the module owner's
decision; this section records the measurement only.

## Transparency: the `rating_methodology` document

`methodology.py` builds the `rating_methodology` season aggregate: how KTPR
v2, MMR and momentum are computed — equations, every variable, and the
current per-map values from `momentum_params.json` — read from the code
that uses them, never retyped. `run_weekly.py` writes
`rating_methodology_payload.json` beside the ratings payload; the workflow
publishes both to `mmr-ratings`; the operator imports either with the same
`report_service.py import-mmr <file>`; `report_sync` publishes it; the
website shows it under Stats. No player rows.
