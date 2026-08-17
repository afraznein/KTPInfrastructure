# Match accumulation Phase C: private positional shadow

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
- teamkill and suicide deductions; and
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

### Last-flag holding without kills

The capture layer already marks a kill made while defending the only remaining
flag, so v1 can score active last-flag defense exactly. It cannot yet prove that
a player spent a no-kill interval holding the team's only remaining flag:
periodic player positions are stored, but periodic flag ownership is not.

That passive state should eventually receive non-zero but lower credit than an
active contest, matching the distinction between a team merely flooding its
last Harrington flag and actually holding it under kills/pressure. Implement it
only after a compact ownership-state timeline is persisted or reliably
reconstructed. Do not infer it from proximity alone.

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

Across the current five Anzio bot matches, this produced 5,905.29 positional
points beside 49,278.30 event points: a **10.70% share of combined points**.
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

The tick is then multiplied by the nearest flag's territory value: own first
`0.50x`, own second `0.80x`, middle `1.25x`, enemy second `1.75x`, or enemy
first `2.25x`. Applicable evidence multipliers stack: `1.25x` for a double-cap
flag, `1.20x` for a reviewed high-contest area, and `1.75x` when an opponent is
within 768 units in that same tick. For example, standing exactly on contested
Anzio middle produces `2.5 * 1.25 * 1.20 * 1.75 = 6.5625` points for the tick.

Confirmed kills defending the team's only remaining flag add 30 points each,
capped at 60 per half. All proximity and defensive-kill points are summed and
then capped at 150 times the player's recorded halves. Only the final derived
components leave the private workspace; coordinates, cells, paths, flag
identities, distances, and personal heatmaps do not.

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

## Next slices

1. Run the v2 profile over real matches and recalibrate its target share,
   radius, point rate, and per-half cap by map, side, and role.
2. Add event timelines for fast multi-kills, trades, reversals, and objective
   conversion without folding them into points immediately.
3. Capture or reconstruct ownership/contested state so proximity can become a
   genuine holding/defending term rather than a location proxy.
4. Compare accumulation rankings to current KTPR and match outcomes in shadow.
5. Keep all individual heatmaps private even if aggregate league/map heatmaps
   are introduced later.
