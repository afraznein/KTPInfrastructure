### `tests`: the e2e lane's migration list claimed four migrations were unapplied in production (2026-10-14)

`DEFAULT_SCHEMA_FILES` carried *"PROPOSED for production"* against migrations
**038, 039, 040 and 042**. All four are applied to `hlstatsx` — 038 since
2026-09-26 — so every one of them was false, and 042's read *"for the same
reason 038 is"*, justifying itself by a claim that had already gone stale.

Verified against the live schema rather than taken from a ledger, with controls
in both directions: `ktp_move_census` and `ktp_aim_vis` present,
`ktp_score_events.round_time_left`, `ktp_flag_captures.provenance` /
`.source_action_id` and the `uk_source_action` index all present; a nonsense
table and a nonsense column both absent.

The comments now give only the reason the **lane** needs each migration — the
mechanical part, which is about this file and does not rot. `dpl-796c` asked for
038 alone; the other three are the same sentence with the same defect, and
fixing one would have left three beside it looking trustworthy.

**The rot is structural, not a typo.** This file lives in a test lane that
stands up its own database. It has no way to observe production, so a production
claim here can only ever be a remembered fact with nothing holding it true, and
it goes stale again on the next apply.

**Tests:** 5, mutation-checked — restoring the old comments reddens the guard,
which names all four offenders.

🔑 So the guard is on the **property**, not on today's four spellings: a comment
in the migration lists may say why the lane needs a migration and may not say
where production stands.

⚠️ And the guard's own self-check earned its keep before review: the first
detector spanned `\W{0,40}` between the state word and `production`, which
cannot cross the `for` in *"PROPOSED for production"* — so it matched **none** of
the four comments it exists to catch. A case asserting the detector fires on
each known-bad wording is what caught it; without it this would have shipped as
a guard that passes because it sees nothing.
