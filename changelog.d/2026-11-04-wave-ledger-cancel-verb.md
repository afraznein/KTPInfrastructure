### `scripts`: a wave unstaged before its swap had no resolved state, so it blocked the next stage for ever (2026-11-04)

The ledger recognised one way for a wave to end: `reconcile`, which closes a wave
that shipped. A wave whose artifacts were deliberately removed before the 03:00
swap never activates, so its row stays pending, and the row-flip gate sits on the
*next* stage — meaning the wave you unstaged blocks the wave that fixes it. The
only escape was `--allow-unreconciled`, which lifts the gate for every wave rather
than resolving one, and leaves a row that still claims an artifact went live.

This happened on 2026-11-04. The `stats_logging` 1.37.0 wave was staged from
`origin/main`, which carried a commit adding `dodx_get_shot_target4` to both the
module and the capture include; only the plugin half was staged, so the `.amxx`
referenced a native the fielded dodx module does not export. AMXX resolves a
plugin's natives at load, so the 03:00 swap would have failed the plugin on all 24
instances and taken the whole stats path with it. The wave was unstaged, and its
ledger row then described an activation that will never occur.

`cancel WAVE_ID --reason "why"` records that state. It reads the fleet and refuses
unless it can show the wave did not ship, because a row saying a wave never
happened, over a fleet running its artifact, is worse than the pending row it
replaces. Four refusals, each with its own test: the artifact is still staged as
`.new` (cancel records an unstage that already happened, so unstage first); no
instance reported the artifact at all (absence unestablished, not proven); the
md5 is live on part of the scope (a partial swap is a wave to finish or roll back);
and the md5 is live on all of it.

That last case is deliberately *not* reported as activation. The ledger records no
replaced md5, so a wave that swapped and a wave that staged bytes already live are
indistinguishable from the fleet — the refusal says so instead of asserting the
more likely of the two. An unreadable fleet is also a refusal rather than a
warning, for the same reason.

`load_waves` now treats cancelled as resolved alongside reconciled, which is what
clears the gate; a mutation reverting that line turns three tests red.
