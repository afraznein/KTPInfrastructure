## Why

The half-leaver correction (#500, `scripts/roster_teams.py`) reached `players[]` and stopped there. Three of the payload arrays the match-report page renders through `sideFor` still carry a team it never touched, and for two of them the cost is worse than a mislabelled row — **they lose rows**.

Measured read-only on `1789952635-NY1`, the specimen `roster_teams.py` is written against. The swap is real in the fixture, not assumed: half 1 is **12 of 12 players on the opposite side**, 0 agreeing with the canonical labels, so this is the one condition under which a raw side and a roster team can disagree.

| array | verdict |
|---|---|
| `trades.events` | raw roster label — and the leaver's frags are **dropped** |
| `fast_multikills` | same feed, same drop; plus `objective_conversion` compares two different spaces |
| `recap_speed` | raw **engine side** by construction, rendered as a league team |
| `duels` | ✅ **already reconciled** — see below |

### `trades` and `fast_multikills`: 11.6% of the match silently discarded

`sql/analytics/frag_timeline_fact.sql` joins `killer_team`/`victim_team` to `ktp_match_players`, which is the side a player held in his LAST half. A half-time leaver carries the opponent's label there exactly as he did in `players[]` before `apply_canonical_teams` — so **both sides of his frags read the same team**, `match_timelines._frag_classification` calls every one an explicit team kill, and the trade and multikill analyzers never see them. That function's own comment calls an explicit same-team row a source-contract violation, because `hlstats_Events_Frags` already excludes teamkills; the violation was ours.

| | before | after |
|---|---|---|
| frags in the competitive set | 518 of 586 | **586 of 586** |
| dropped as `explicit_same_team` | **68** | 0 |
| trade events | 99 | **120** |
| fast multikills | 87 | **109** |
| `deaths_traded` | 99 | **120** |
| `team_death_response_rate` | 0.1911 | **0.2048** |
| per-team trade kills | (1: 41, 2: 58) | **(1: 55, 2: 65)** |

### `objective_conversion`: credited to the opponent in a swapped half

`objective_timeline_fact.sql` maps the capture's team NAME onto 1 = Allies / 2 = Axis — engine side. `_attach_objective_conversion` compares it against the killer's report team, so in any swapped half it matched the **opponent's** captures: a conversion denied to the side that made the kills and handed to the side that did not.

Half 1 goes from **12 of 34 sequences converted to 31 of 56**. Half 2 — the terminal half, where the two conventions agree by construction — **does not move at all**, which is the built-in control for the whole change.

### `recap_speed`: a per-team total that is a mixture of both rosters

Keyed on `ktp_flag_state_events.owner_team`, the engine side that owned the flag, while the page renders `events[].team` and `teams[].team` as league teams. Every half-1 recap was labelled with the opponent, and `teams[]` sums across halves **by side**, so each published row is part of one roster and part of the other: **(side 1: 47, side 2: 39) where the report teams really took 44 and 42.** `teams` is therefore re-aggregated from the translated events rather than relabelled — averaging engine-Allies across two halves that belong to different report teams was never a meaningful number.

### `duels` is already correct — recorded so nobody re-checks it

The DTO's `duels` array carries **no `team` field at all** (`{killer, victim, kills}`), and `build_duel_matrix` takes its `cross_team` from the corrected `players`, not from the frag feed. Nothing is owed here.

## What changed

- `roster_teams.restamp_frag_teams(frags, players)` — stamps the frag feed from the **already corrected** `players` rather than re-deriving a team from the life feed. One place decides a player's team and this reads its answer, which is this workstream's own rule. A restamped row keeps the original under `*_roster_team`.
- `report_team_convention.translate_objective_timeline` and `translate_recap_speed` — two more translators on the existing layer, with the same drop-the-unresolvable-half-with-a-caveat rule as `translate_map_control` / `translate_team_series` / `translate_capouts`.
- `match_analytics.build_report` restamps the frag feed next to the `apply_canonical_teams` call, and the single `report_team1_engine_side` resolver is hoisted above `build_shadow_timelines` (it was computed later for the three existing consumers; there is still exactly one call).

**No contract or DTO shape change.** `team_convention` and `engine_side` stay inside the internal report. The published *values* change, which is the point.

## Scope held deliberately

`positional_shadow`, `accumulation_v3`, `damage_conversion` and `flag_fights` also read a `killer_team`, from their own feeds. **None of them was measured here and none is touched.** `interruptions.py` already resolves sides from the life feed itself and documents this exact trap.

## Verification

CI's own unit command in a dedicated worktree, baseline first:

- **base** (`origin/main`, `24e295b`): 391 failed, 2656 passed, 186 skipped
- **head**: 391 failed, **2674 passed**, 186 skipped — **+18 passed, +0 failed**, and the two `FAILED` lists are **byte-identical** (`comm` empty both ways)

The 391 are pre-existing and environmental on this box: `pwd`-only imports and `charmap` decode errors from a Windows default locale. They are untouched and green on CI's Linux runner. The four `pwd`-importing files are excluded from the run on both sides.

The 18 new tests are 6 on `restamp_frag_teams`, 9 on the two translators, and 3 end-to-end through `build_shadow_timelines` pinning the swap-half case: the raw feed drops the leaver's frags (asserted via `explicit_same_team_rows == 2`), the restamped feed recovers them with the leaver on his own team, and the conversion flips from `False` to `True` once the capture feed is translated. The byte-identical case is asserted too — a report with no leaver comes out unchanged.

Coordination-Workstream: infra-half-side-correction

