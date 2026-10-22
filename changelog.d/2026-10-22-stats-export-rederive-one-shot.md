### `scripts`: a one-shot `--rederive` for the exporter, so a corrected match can be landed (2026-10-22)

`keep-the-prac`#1008 taught the site to re-derive a fixture whose stored payload
is unchanged: `payload.ts` accepts `rederive` and `ingest.ts` widens the
re-derive list with it. That half works. Nothing produced the flag.

Measured 2026-10-22, each with a positive control in the same file: the deployed
`/usr/local/bin/ktp-stats-export.py` greps **0** for `rederive` against `payload`
×10, and `scripts/ktp-stats-export.py` on `origin/main` **also** greps 0 against
the same control — so this was not a deployment gap, the producer was never
written. No route under `src/app/`, no npm script, and the only non-test
occurrence anywhere was the doc describing the field.

The consequence is why it sat unnoticed rather than failing: the field defaults
to false, so every ordinary export re-derives nothing, which is
indistinguishable from a re-derive that ran and changed nothing. `dpl-833b`'s
deliverable was unreachable, not forgotten, and the two half-leaver matches are
still wrong on the site.

`--rederive` now carries it. Three things about the shape, each deliberate:

**It is a CLI flag and there is no config key or environment variable.** The
export timer fires every ~10 minutes; anything persistent would re-derive
forever, and a re-derive on every tick is as meaningless as one that never runs.

**It requires `--match-id`.** Re-deriving a whole window has no named
beneficiary, and the case this exists for — a match corrected upstream — is
always one match at a time. The refusal happens before `load_config` and `Db`,
so a mis-invocation cannot reach the database; a test asserts that by making
both explode if reached, with the `--match-id` form as its positive control.

**It bypasses the sent-state dedup, and that is the part worth reviewing.**
`skips_sent_state()` is now a named pure function instead of an inline boolean.
A re-derive of an *unchanged* payload is the entire use case, so a run filtered
out as "nothing new to export" would report success and do nothing — the same
silent shape as the default-false field. `--match-id` already forces the bypass
and `--rederive` requires it, so the term is redundant today; it is named anyway
because a guarantee resting on a coincidence between two other flags is one
refactor from being lost.

`build_payload()` is extracted as well, so the one assertion worth making about
the flag can be made: it reaches the wire only when asked for, and an ordinary
export's body is byte-unchanged. `--dry-run` now prints the real body rather
than an approximation of it, so `--dry-run --rederive --match-id X` shows
whether the flag is carried before anything is POSTed.

Ten tests, mutation-checked: dropping `args.rederive` from `skips_sent_state`,
making `build_payload` always set the key, and removing the `--match-id` guard
each redden exactly one test and nothing else.
