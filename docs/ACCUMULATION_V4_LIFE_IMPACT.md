# Accumulation v4: per-life positional impact

Status: **experimental shadow; not KTPR**

This iteration keeps the bounded v3 combat and objective model and replaces
continuous objective-proximity scoring with outcome-led per-life impact. Every
generated match report embeds the exact active configuration, player component
table, evidence limitations, and a worked scoring example so reviewers can
evaluate that iteration without consulting this design document.

## Public components

Only five derived player totals may leave private processing:

1. `mid_defense_points`
2. `aggression_points`
3. `enemy_flag_hold_points`
4. `active_flag_defense_points`
5. `sequence_continuity_points`

Their sum is the existing public `position_points` field. Coordinates, routes,
sample histories, nearest-flag observations, and per-life timelines remain
private.

## Life boundaries

Explicit spawn/life events are preferred. When absent, a shadow report may
reconstruct life numbers using enemy deaths, teamkill deaths, suicides, half
boundaries, and the next observed position sample. The quality gate must say
`WARN`; inferred lives may never be represented as explicit telemetry.

An immediate death receives zero positional impact rather than a penalty.

## Defensive evidence

Defense requires more than a player's proximity to a flag. The scorer requires:

- a canonical capture or trustworthy ownership event establishing that the
  player's team currently owns the flag;
- one or more opposing position samples inside the configured threat radius;
- the player inside the objective radius; and
- for kill bonuses, a kill aligned to the player's nearest sample within the
  configured tolerance.

Mid defense has its own presence and kill terms. Other owned flags award an
active-defense kill term. Unknown ownership produces no defense points.

## Forward play

Reviewed map topology classifies the nearest objective for each team as own
first, own second, middle, enemy second, or enemy first. Samples whose nearest
objective is past mid can earn forward-pressure points. The first such sample
in a life receives a crossing award.

Forward presence under nearby enemy pressure has the highest continuous value.
Unopposed forward presence remains positive but uses a small multiplier.

Presence inside the tighter objective radius of an enemy-side flag is scored
separately. It requires nearby opposition or friendly ownership established by
a canonical capture. Unopposed friendly holding decays with time.

## Same-life continuity

The scorer rewards verified state transitions while a player remains alive and
contributes to the capture through credit or a recent kill:

- defense → mid capture;
- defense → forward push;
- mid capture → forward push; and
- forward push → enemy-side capture.

These points describe the territorial outcome. They do not repay the kills,
damage, streak, or fast chain that supplied the combat evidence.

## Guardrails

- No negative components.
- Fixed per-life continuity cap.
- Fixed total positional cap per life.
- Fixed total positional cap per player per match.
- Capture and conversion pools remain bounded independently.
- Missing topology, flags, ownership, or samples disables the dependent term.
- Raw private spatial or life records are prohibited from public bundles.

The active constants live in
`config/analytics/accumulation_v4_life_impact.toml`. Their values are copied
into each machine-readable report and rendered into that iteration's Markdown
explanation.
