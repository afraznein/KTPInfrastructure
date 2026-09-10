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
