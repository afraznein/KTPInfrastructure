### `dto`: KAST-F is published as a percentage, not only as a z-score index (2026-10-02)

KAST-F is a **share** — the fraction of flag fights in which a player got a kill, got an assist,
survived, or had their death traded. It was published only on the KTPR display index,
`max(50, 100 + 15·z)`, so a strong KAST rendered as **125**. That reads as "125%", which is
impossible for a share; it actually means +1.67σ against the match average.

The report now carries `kast_f_pct` on each KTPR player row, in natural units (0–100, one
decimal). Render that as the KAST figure. `components.kast_f` stays, and belongs beside it as a
"vs match average" comparison — never on its own.

`KTPR_DISPLAY_SCALE` gains a `kast_f_pct` entry describing it as `percent`, which is where a
consumer already looks to tell a scaled field from a raw one. Its note says outright that the
index is **not** a percentage, because that is the specific mistake it exists to prevent.

`null` means **not measured**, and must render that way rather than as 0%. `flag_fights`
suppresses `kast_f` entirely when the assist or trade source is unavailable, instead of emitting
a smaller number — an absent trade feed would otherwise read as "never got traded", which is a
real penalty rather than missing data. Publishing 0% would reintroduce exactly that lie.

Second time this index has been mistaken for the quantity: a consumer previously read the
model's `normalization: per_match_z_scores` metadata as describing the published `rating` and
applied a second z-transform, saturating every value to exactly 100.0 on every match page
(keep-the-prac #679/#691). The `display_scale` block was added then. This is the same class of
confusion one level down, in a field whose natural unit makes the index actively misleading.
