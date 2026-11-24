### `scripts`: the row-flip gate requires the row's CLAIM, not an md5 anywhere on it (2026-11-09)

`gate()` decided whether an activated wave's version row had been flipped using
`check_row()` alone, and marked the wave reconciled when it passed. `check_row()`
answers a narrower question than the gate needs — whether the row *carries* an
md5 — and the staging convention writes the incoming md5 into the row tail at
stage time. So the gate's condition was satisfied from the moment a wave was
staged, hours before activation, by the very sentence recording that the row was
not flipped yet.

On 2026-11-09 a wave activated at 03:00 ET with two rows still naming the
outgoing build. `check` reported the wave reconciled and `status` reported no
unreconciled waves, while `sweep` reported `ROW_NOT_LIVE` on both artifacts
against the same text at the same moment. Because `gate()` auto-clears, the
diagnostic run also consumed the ledger entry, so nothing would have raised it
again.

`gate()` now additionally requires `row_claim()` — the row's first md5, which by
the table's convention is the build it says is live — to equal the activated
md5. `sweep` already asked this; the gate did not, although `row_claim()` is pure
text and needs no fleet read.

`check_row()` is unchanged. Its presence semantics are correct for its own
question and relied on elsewhere: rows legitimately name superseded builds and
backup paths, and a flipped row still carries the outgoing hash as its rollback
pin. The claim leg therefore applies only where a row exists — an unmapped
basename such as `hlds_linux` keeps the documented weak file-wide check, which
`row_claim()` cannot speak to.

One existing test was misleading in a way that helped this survive:
`test_a_prior_build_named_in_the_same_row_is_not_a_pass` asserted that a prior
build *does* pass, under a docstring reading "Only the CURRENT md5 satisfies the
check". The name and docstring stated the opposite of the assertion, so reading
the suite gave the wrong model of `check_row()`. Renamed to say what it checks,
and it now points at the gate test for the part it does not cover.

Three cases cover the fix, and the first fails on the previous code:

- a row carrying the incoming md5 in its tail while claiming the outgoing one
  blocks the gate, and the wave is not consumed;
- a correctly flipped row clears the gate even though the outgoing md5 is still
  present as its rollback pin — the control that stops the fix overreaching;
- an unmapped basename still clears via the weak file check.
