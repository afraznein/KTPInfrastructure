# Public match report v1 development candidate

Status: `development_candidate`  
Packet version: `v1.2.0-development_candidate`  
Payload contract version: `1.2.0`  
Privacy review date: 2026-08-29

This `v1.2.0-development_candidate` supersedes the unreleased v1.0 and v1.1
development candidates. It is not wire-compatible with their incomplete
payload versioning and must be consumed as the three family names plus the full
`contract_version: 1.2.0`; no earlier candidate is a production release.

## Public documents

The website may consume only these three validated documents:

- `public-report-v1`: team-separated descriptive box scores;
- `public-timeline-v1`: producer-precomputed aggregate team points and team
  momentum; and
- `momentumEpisode-v1`: producer-precomputed sanitized team episodes.

The website displays these values as escaped text/numbers. It does not infer
teams, calculate statistics or scoring, classify episodes, repair
conservation, or join private inputs.

## Restricted data

Player Elo, Bradley-Terry, accumulated/overall/impact ratings, raw or
normalized player points, player ranks, allocations, ledgers, scoring
components/profiles, database/platform/stable IDs, and individual spatial
evidence are restricted tool-developer data. They have no field in these public
schemas. Spatial maps and atlases are explicitly deferred from this packet.

Public JSON has no provenance fields. Analytics box-score input schema 3,
private scoring schema 1, public schema reconciliation, source paths, and file
hashes exist only in this packet's private manifest/docs.

## Team contract

Every document uses exactly `team_a` and `team_b`. The report supplies a safe
display name and an explicit side (`allies`, `axis`, or `unknown`) for every
played half. Timeline bins, conservation rows, annotations, and momentum
episodes may reference only those two match-scoped keys. Integer/faction team
IDs are never inferred by the exporter.

## Value privacy and display names

The exporter uses closed statuses and reason codes. It never copies upstream
readiness, confidence, or coverage prose. The recursive guard rejects sensitive
values as well as keys, including Steam identifiers, long numeric identifiers,
actor/database references, HMAC/audit identity material, rating vocabulary,
positional vocabulary, paths, URLs, and provenance wording. Key matching is
performed on punctuation-stripped case-folded text and rejects restricted
tokens embedded in longer keys (for example `internal_player_id_copy`); the
single `privacy.player_identity` declaration is an explicit schema-owned
allowlist entry, not a general identity exception.

Short protected value terms use explicit punctuation-stripped concatenation
patterns. They reject direct-prefix forms when the term is adjacent to numeric
payloads or private identity/data vocabulary such as HMAC or HMAC-audit
identity/ID/key/private-key/digest/signature, player rank/ranking, score, value,
data, or samples. Standalone
protected terminology remains rejected by lexical-boundary patterns. Incidental
substrings in ordinary names are not restricted, so compatibility does not
depend on a static name allowlist. New private suffix vocabulary must be added
to these patterns and negative fixtures before it is relied upon at the public
boundary.

Player/team display names are the sole prose exception. They are NFKC
normalized, limited to 1-64 characters, reject control characters and
sensitive identifier/path/URL patterns, and must be rendered by the consumer
as escaped text. Markup-looking characters are data, never trusted HTML.
Ordinary competitive map tokens such as `dod_anzio` and ordinary names without
restricted vocabulary remain valid.

`clip_ref` is either null or an opaque server-issued token matching exactly
`clip_[a-f0-9]{32}`. The body is scanned like every other public string, so an
otherwise well-formed token containing a 12-or-more-digit run is invalid.
URLs, paths, Steam IDs, mixed-case tokens, and bare numeric IDs are invalid.

## Numeric domains

The producer, semantic validator, and schemas enforce the same closed domains:

- played halves: 1-10;
- match duration and event/bin times: 0-21,600 seconds;
- public bin width: 1-300 seconds;
- descriptive counts and damage: 0-1,000,000;
- aggregate team points and reconciled totals: 0-1,000,000,000;
- reconciliation deltas/differences: -1,000,000,000 to 1,000,000,000; and
- momentum endpoints, changes, swings, and contributions: -1,000,000 to
  1,000,000.

All numeric values must be finite. These are validation/privacy bounds, not
competitive targets. Changing one requires a new contract version.

## Null, zero, and coverage

- `unavailable` metric -> JSON null, `confidence: unavailable`, closed reason;
- `available` or `low_sample` metric -> finite numeric value;
- verified zero remains numeric zero;
- low sample remains a value and uses the `low_sample` status/reason; and
- team additive totals must equal their player rows.

The first box-score slice includes kills, deaths, plus/minus (`kills - deaths`),
assists, headshots, teamkills, suicides, damage dealt/taken/differential,
capture credits, cap breaks, shots, hits, and descriptive raw accuracy.
Teamkills and suicides are null/unavailable when their source is absent.

Missing timeline values remain null. Bin/half/top coverage is downgraded, and
conservation becomes unavailable when required totals are missing.

## Timeline reconciliation

Event bins contain only time-attributable `points_gained` and
`cumulative_points`. Untimed score is never injected into a bin. Each team may
have one half-end annotation. Its numeric `untimed_reconciliation_delta` exists
only once, in that team's conservation row; it is not duplicated in the
annotation or a bin. The optional reconciled total obeys both published equations:

```text
timed_total = sum(points_gained)
reconciled_total = timed_total + untimed_reconciliation_delta
```

Both differences and a `pass`, `fail`, or `unavailable` status are producer
outputs. A browser must not recompute or silently repair them.

Within each half, cumulative points reset to zero and every available value
obeys `cumulative_points[n] = sum(points_gained[0..n])`. Momentum also resets
to a zero baseline and every available pair obeys
`momentum_change[n] = momentum[n] - momentum[n-1]`. A null or missing member of
either cumulative/gain or momentum/change pair breaks that recurrence. Later
cumulative or momentum values cannot silently resume the unverifiable chain;
there is no implicit mid-half reset.

Complete bins start at zero, are ordered, non-overlapping, and contiguous.
Every non-final bin has exactly `bin_seconds` width; only the final bin may be
shorter. Gaps or irregular widths require explicit
`partial/irregular_interval` coverage. Complete timeline coverage requires
every half `1..halves_played`, and the sum of half end times must equal the
report duration. Episodes must fall within a played timeline half.

## Momentum contract

Episodes require `end_time >= start_time` and
`swing = end_momentum - start_momentum`. Contribution equals that team momentum
swing and uses the `momentum_index` unit. Episodes are canonically sorted and
their stable ID is derived from canonical sanitized contents.

Approved reasons are `capture`, `cap_break`, `capout`, `three_kill_chain`,
`multi_kill_chain`, `opening_duel`, `trade_kill`, `objective_hold`,
`flag_defense`, `combat_swing`, `territory_pressure`, `mixed`, and
`insufficient_evidence`. Empty output has explicit
`unavailable/no_episodes` coverage.

## Serialized atomic publication

Publishers use an adjacent exclusive directory lock, wait for a bounded period,
and heartbeat the lock while publishing. A lock cannot be considered stale for
less than 300 seconds (900 seconds by default). A stale lock is atomically
renamed to a unique quarantine before deletion and reacquisition. Publication
writes a unique adjacent temporary directory, moves any complete old bundle to
a unique backup, and then renames the complete new bundle into place. Invalid
existing directories are refused. Normal success, failure rollback,
concurrent publication, and stale-lock recovery leave no temp, backup, lock, or
quarantine directories.

## Frozen packet validation

From the frozen packet directory:

```powershell
python -B implementation/validate_public_report_v1.py .
python -B implementation/test_packet.py
```

Verify every `SHA256SUMS` entry:

```powershell
Get-Content SHA256SUMS | ForEach-Object {
  $hash, $relative = $_ -split '  ', 2
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $relative).Hash.ToLower() -ne $hash) { throw "Hash mismatch: $relative" }
}
```

The packet includes sanitized synthetic producer inputs, schemas, goldens,
negative cases, implementation modules, and a standard-library packet-local
test runner. It does not require the source worktree, Denver data, or map
assets. JSON Schema validation requires `jsonschema>=4.18`. The frozen
validator loads exactly 156 uniquely named negative cases; a missing,
duplicated, or silently added case makes the inventory invalid.
