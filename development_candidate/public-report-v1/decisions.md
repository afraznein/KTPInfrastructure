# Decisions

1. Public payloads contain no provenance fields or upstream prose.
2. Closed public codes replace readiness/confidence/coverage messages.
3. Privacy scans values and keys; display names have a separate strict text
   policy and still require consumer escaping.
4. All documents use exactly `team_a` and `team_b`; side-per-half mappings are
   mandatory and no integer/faction inference is allowed.
5. Teamkills, suicides, and plus/minus are part of the authoritative first
   box-score slice. Missing teamkill/suicide sources remain null.
6. Aggregate team timeline points are allowed; player points, ratings, ranks,
   components, allocations, and ledgers remain restricted.
7. Untimed reconciliation is half-end metadata, never an event-bin spike. Its
   numeric delta occurs once in conservation; the annotation is marker-only.
8. Builder validation completes in memory before a serialized temporary-
   directory swap. An adjacent exclusive lock has bounded waiting, heartbeat,
   a 300-second minimum stale threshold, and quarantine-before-reclaim.
   Non-finite stale thresholds are rejected before lock inspection. After a
   stale-owner crash, the next lock holder restores a valid pre-swap backup
   when installation never completed, preserves an already installed bundle,
   and removes orphan temporary, backup, and lock-quarantine directories.
   Existing directories must already be exactly one complete bundle; unknown
   files cause refusal rather than deletion or mixing.
9. Momentum reasons are a closed analytics-only enum; episode IDs derive from
   canonical sanitized content.
10. The frozen packet is self-contained and includes synthetic producer inputs
    and a packet-local standard-library test runner.
11. Spatial maps/atlases are deferred. No artwork, geometry, cells, vectors,
    routes, or positional fixtures are in this packet.
12. All three public families carry the full compatible payload contract
    version `1.2.0`; family names remain stable schema identifiers.
13. Numeric privacy domains are fixed at 10 halves, 21,600 seconds, 300-second
    bins, 1,000,000 descriptive facts, 1,000,000,000 aggregate points, and
    +/-1,000,000 momentum/contribution.
14. Timeline recurrence resets to zero per half. A null member of either
    cumulative/gain or momentum/change pair ends that half's public recurrence;
    later cumulative or momentum values cannot resume without an explicit
    contract reset (none exists in v1). Complete intervals are contiguous and
    normally full-width, with only a shorter final bin allowed.
15. Deep privacy matching treats punctuation/case-normalized HMAC and audit
    identities, rating vocabulary, positional vocabulary, source-schema terms,
    and embedded private-ID key variants as restricted. Short protected value
    terms use explicit normalized adjacency patterns for numeric payloads and
    shared HMAC/(HMAC-audit) identity/ID/key/private-key/digest/signature,
    optional-player rank/ranking, and score/value/data/ID/sample vocabulary,
    while incidental substrings in
    ordinary names remain compatible without a static allowlist. Standalone
    protected terms still use lexical-boundary matching. The schema-owned
    `privacy.player_identity` declaration is the sole explicit key exception.
16. Negative-fixture inventory is exact and unique, not a lower-bound check;
    this revision contains 156 cases.
