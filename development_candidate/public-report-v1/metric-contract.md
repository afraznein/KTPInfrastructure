# Public match report metric contract v1.2.0

This is a public projection of `docs/MATCH_METRIC_CONTRACT_V1.md`; it does not
change private analytics or scoring formulas.

## Box score

The public first slice is team-separated and contains display name/team key,
kills, deaths, plus/minus, assists, headshots, teamkills, suicides, damage
dealt, damage taken, damage differential, capture credits, cap breaks, shots,
hits, and raw accuracy.

`plus_minus = kills - deaths`. `damage_differential = damage_dealt -
damage_taken`. `raw_accuracy = hits / shots` and is null when shots are zero or
inputs are unavailable. Raw accuracy remains descriptive and is not a rating.

Kills, deaths, assists, headshots, teamkills, suicides, damage, capture
credits, cap breaks, shots, and hits are additive. A team value is available
only when every player value is available, and must equal the player sum.

Every metric has closed `availability`, `confidence`, and `reason_code` fields.
Null/status contradictions are invalid, not presentation choices.

## Team identity

`team_a` and `team_b` are match-scoped public keys. `display_name` is validated
display text. `side_by_half` explicitly records faction side for every played
half. No consumer maps database IDs or assumes that Allies/Axis is a stable
team across halftime.

## Team timeline

Every bin is producer-precomputed and contains aggregate team
`points_gained`, `cumulative_points`, momentum, momentum change, and coverage.
No player/components/allocations exist. Missing input remains null and lowers
coverage.

At the start of every half both cumulative points and momentum use a zero
baseline. Each available cumulative value equals its preceding cumulative plus
that bin's gain; each available momentum change equals the current momentum
minus the preceding momentum. A null or missing member of either recurrence
pair ends that chain for the half: later cumulative or momentum values cannot
resume it, and no implicit mid-half reset exists. Complete bins start at zero,
are contiguous, and have `bin_seconds` width except for an optional shorter
final bin. Irregular bins require explicit partial coverage.

Untimed aggregate score appears numerically once in the conservation row as a
half-end reconciliation delta. The half-end annotation is a marker and does
not duplicate the value. It is not a bin gain. Conservation publishes the
timed sum/final total, delta, reconciled total, both differences, and status.

## Momentum episodes

Episodes are analytics-produced. Time, endpoints, swing, direction,
contribution, closed reasons, confidence, coverage, and optional opaque clip
token are validated. Canonical ordering and content-derived IDs make output
deterministic. A browser cannot infer reason codes.

Episodes are limited to a played half present in the timeline and cannot extend
beyond that half's final bin. Clip references are null or a lowercase opaque
`clip_` token with exactly 32 hexadecimal characters and no long decimal run.

## Numeric validation domains

Halves are 1-10; duration/event time is 0-21,600 seconds; bin width is 1-300
seconds; descriptive counts/damage are 0-1,000,000; aggregate points are
0-1,000,000,000 with symmetric reconciliation deltas/differences; and momentum
and contribution are -1,000,000 to 1,000,000. Values outside these domains or
non-finite values fail closed.

## Deep privacy validation

Keys are case-folded and stripped of punctuation before restricted-token
matching, including tokens embedded inside longer names. String values retain
their original boundaries and are also checked after normalization. HMAC/audit
identity and audit-ID/key/private-key/digest/signature material,
Elo/rating/(player-)rank vocabulary, and
positional vocabulary such as `posx`, position samples, coordinates, routes,
cells, and spatial fields are not public facts. This applies to map and display
text as well as opaque tokens.
Ordinary map names and display names that do not contain restricted vocabulary
remain allowed and still require escaped rendering.

## Change control

Any field/formula/reason/null/privacy change requires a version bump, new
goldens, negative-case review, manifest/checksum regeneration, and an explicit
historical-recompute decision.
