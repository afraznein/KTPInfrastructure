# Match accumulation Phase C: private positional shadow

> This document preserves the v0-v2 positional experiment. The current local
> scoring iteration is the no-penalty, fixed-budget
> `accumulation_v3_bounded` model documented in
> `ACCUMULATION_V3_BOUNDED.md`. Existing v0-v2 artifacts remain reproducible
> and are not rewritten.

Phase C starts the accumulation-style analysis without waiting for public API
or rating work. It remains local and shadow-only. It does not replace KTPR.

## Privacy contract

Individual positional samples may be used to calculate a player's accumulation
points, including a private per-player heatmap. That working data is classified
`PRIVATE_PLAYER_POSITIONAL_ANALYTICS` and must not be sent to the website,
public API, downloadable reports, Discord, or another player.

The shareable result may contain one derived `position_points` value per player.
It may not contain grid cells, coordinates, nearest-flag identity, flag-level
sample counts, distances, paths, or individual sample coverage. The exporter
has a recursive deny-list assertion so a future edit fails before writing a
shareable artifact if one of those fields leaks.

Private and shareable outputs must use different directories. Private JSON is
created with owner-only permissions where the operating system supports them.

## v0 accumulation ledger

The first profile accumulates transparent components:

- kills;
- assists;
- capped damage;
- capture credits;
- cap breaks;
- historical v0 teamkill and suicide deductions (removed in v3); and
- capped objective-proximity points calculated from private position samples.

Position is intentionally a small term. Each sample represents the configured
five-second interval. Credit decays linearly from a flag coordinate to zero at
512 units and is capped at 100 points per recorded half. This prevents passive
presence from overpowering event production while we lack contested-state,
visibility, role, spawn-wave, and flag-ownership context.

The values in `config/analytics/accumulation_v0.toml` are experimental starting
values for sensitivity analysis. They are not production KTPR weights.

## v1 scenario-aware position points

`accumulation_v1` keeps the same 100-point per-half positional ceiling but
changes how proximity earns points inside it:

| Scenario | Treatment |
|---|---|
| Enemy first flag | Highest proximity multiplier (`2.25x`). This is the deepest pressure, nearest the enemy spawn. |
| Enemy second flag | High proximity multiplier (`1.75x`). |
| Middle | Elevated base (`1.25x`) and an additional reviewed-hotspot multiplier (`1.20x`). |
| Double-cap flag | Additional `1.25x` while close enough to contribute. |
| Active contest | Additional `1.75x` when an opposing player is sampled within 768 units in the same five-second tick. |
| Own second | Reduced base (`0.80x`). |
| Own first, without confirmed pressure | Low base (`0.50x`) so empty camping receives some credit but less than active play. |
| Confirmed last-flag defensive kill | 15 contextual points per kill, capped at 45 per half and still inside the overall positional ceiling. |

Multipliers are applied to the distance-decayed tick, not to the player's whole
score. The active-contest bonus is deliberately stronger than the static
hotspot bonus: an historically busy area should matter, but direct evidence
that both teams are there matters more.

Anzio's reviewed topology currently maps Laundry/Plaza to the Allies' first and
second, Street to middle, and Bridge/Hill to the Axis second and first. Bridge
and Plaza are the two-player capture points. Other maps receive only base
proximity until their topology is reviewed; guessing orientation would award
deep-pressure points to the wrong team.

### Ownership and last-flag holding

Migration 015 adds an event-based `ktp_flag_state_events` timeline. The plugin
emits one baseline row per flag when match context becomes available and then
only owner changes. Joining each position sample to the most recent preceding
state for its nearest flag distinguishes holding, attacking, neutral presence,
and defense under pressure without storing ownership every five seconds.

When a complete baseline proves that a team owns exactly one flag, passive
nearby holding receives a small `1.10x` premium. A nearby opponent raises an
owned-flag tick to `1.15x` before the existing active-contest multiplier, and a
confirmed defensive kill remains the stronger 30-point event. If even one flag
lacks known ownership, last-flag classification fails closed rather than
mistaking an incomplete timeline for a last stand.

The defensive-kill sub-cap is intentional. Early testing at 50 points per kill
made last-flag defense consume 2,778 of 3,514 positional points and pushed 25 of
60 player-match rows to the overall ceiling. Fifteen points with a 45-point
per-half maximum preserves the active-defense premium while keeping sustained
enemy-first/enemy-second pressure as the highest positional opportunity.

## v2 provisional 10% profile

`accumulation_v2_target10` raises the proximity rate from 0.20 to 0.50 points
per second, the per-half positional ceiling from 100 to 150, and confirmed
last-flag defensive kills from 15 to 30 points with a 60-point sub-cap. The
scenario multipliers and radii are unchanged from v1.

Across the current five Anzio bot matches, the per-map version produced
5,870.98 positional points beside 49,278.30 event points: a **10.65% share of
combined points**.
Ten of 60 player-match rows reached the 150-point ceiling. Compared with v1,
12 rows changed rank and none moved more than one place. This is a useful
provisional shadow target, not a human-match calibration or a production KTPR
change.

### Exact positional calculation

For each alive-player sample, the accumulator finds the closest flag in the
2D map plane. Given player `(x, y)`, flag `(fx, fy)`, and distance `d`:

```text
d = sqrt((x - fx)^2 + (y - fy)^2)
proximity = max(0, 1 - d / 512)
base_tick = 5 seconds * 0.50 points/second * proximity
```

A sample farther than 512 units from every flag earns zero. At the flag origin,
the base tick is 2.5 points; halfway to the radius edge it is 1.25.

The tick is then multiplied by the reviewed value of that exact flag for the
player's team. Anzio currently assigns Allied and Axis players different
Street values (`1.40x` and `1.10x` respectively), because Allied control is
judged harder. Generic own-first (`0.50x`), own-second (`0.80x`), middle
(`1.25x`), enemy-second (`1.75x`), and enemy-first (`2.25x`) values are only a
fallback for maps or flags without a reviewed override.

Applicable evidence multipliers stack: `1.25x` for a double-cap flag, `1.20x`
for a reviewed high-contest area, and `1.75x` when an opponent is within 768
units in that same tick. Captured ownership adds `1.10x` while attacking,
`1.15x` while defending an owned flag under pressure, and another `1.10x` for
a proven last-flag hold. Ordinary holding and neutral presence remain `1.00x`.
When no ownership timeline exists, every ownership factor is `1.00x`, exactly
preserving the pre-migration score.

Confirmed kills defending the team's only remaining flag add 30 points each,
capped at 60 per half. All proximity and defensive-kill points are summed and
then capped at 150 times the player's recorded halves. Only the final derived
components leave the private workspace; coordinates, cells, paths, flag
identities, distances, and personal heatmaps do not.

### Map-specific calibration

Flag order does not imply equal map geometry. Each reviewed map therefore owns
two explicit multiplier tables in `map_objectives.toml`: one value for every
flag from Team 1's perspective and one from Team 2's. This supports:

- equal weights for Harrington's lateral first/second objectives;
- asymmetric Anzio middle weights;
- a more even Lennon middle; and
- Saints' genuinely linear increase into enemy territory.

Only verified Anzio identifiers are configured today. Other maps must not be
added from assumed flag order: first verify their canonical flag names and
orientation, then seed provisional weights from map knowledge. Once real match
data exists, compare side-specific control time, capture probability, hold
duration, and conversion to the next capture or capout. A flag routinely held
by the opposing team should generally decrease in value for that side; a rare,
sustained hold should increase, with sample-size limits and manual review so a
single season or team does not cause unstable weights.

The new timeline makes ownership-based calibration possible once real matches
have populated it. A suitable statistic is the attacking side's share of
eligible time controlling each flag: common offensive control lowers the flag
value and rare sustained control raises it. The estimate must be pooled over
enough matches, separated by side, shrunk toward the reviewed starting value,
and versioned rather than rewritten continuously.

## Run locally

Run in the network-disabled Lane B image so the fixture is restored only to an
ephemeral database:

```powershell
docker run --rm --network none -v "${PWD}:/work" -w /work ktp-lane-b:dev `
  python3 scripts/match_accumulation.py `
  build/hlstatsx-fixture.sql `
  --output-dir build/accumulation/shareable `
  --private-output-dir build/accumulation/private
```

The command defaults to `accumulation_v2_target10`. Pass `--profile
config/analytics/accumulation_v1.toml` for the lower-weight scenario profile or
`--profile config/analytics/accumulation_v0.toml` for the flat-proximity
baseline.

Review the shareable Markdown first. The private JSON exists only to audit how
the positional point term was produced.

Generate the non-player flag catalog, control-duration table, and reviewable
map-weight draft with:

```powershell
python scripts/flag_ownership_report.py build/hlstatsx-fixture.sql `
  --match-id MATCH-ID --output build/FLAG_OWNERSHIP_REPORT.md
```

This report is aggregate-only and contains no player coordinates or personal
heatmaps.

## Next slices

1. Run the v2 profile over real matches and recalibrate its target share,
   radius, point rate, and per-half cap by map, side, and role.
2. Add event timelines for fast multi-kills, trades, reversals, and objective
   conversion without folding them into points immediately.
3. Validate migration 015 baselines and transitions in Lane B, then compare
   ownership-derived hold/attack durations against capture events.
4. Compare accumulation rankings to current KTPR and match outcomes in shadow.
5. Keep all individual heatmaps private even if aggregate league/map heatmaps
   are introduced later.
