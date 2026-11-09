### `scripts`: the freshness guard runs an installed copy that is behind, never one that is edited (2026-11-09)

The nightly post-restart soak shells out to an installed `ktp-verify-deploy`. Leg 2 of the
installed-copy check demanded the blob at the tip of `origin/main`, so a merge that moved
`scripts/ktp-verify-deploy.py` made the installed copy stale, the guard refused, and the soak
reached no verdict at all — invisible until someone read the log. Cron has no checkout to
refresh, so "refresh the checkout" is not advice that path can take, and a check that stops
producing a verdict is the failure this module exists to prevent arriving one level up.

- `ktp_script_freshness.py`: for a copy outside any checkout, leg 2 now asks whether the bytes
  are *some* committed version of the row's `source_path` on the fetched ref, not the tip. The
  discriminator is the object graph, not a date, a version string or the row's own commit: the
  bytes' blob id against the blob ids of that path across `_HISTORY_WINDOW` commits of the ref.
  Three git calls whatever the depth of history — `hash-object`, one `log`, one
  `cat-file --batch-check` — so a long-lived path does not put its history on every run.
- Accepting is said out loud, on one line: `is BEHIND <ref> but unedited`, naming the commit
  whose version it is and `ktp-install --report --against-ref` as the way to refresh it.
  Staleness has to read as staleness rather than as the check's own failure.
- Bytes that are no committed version of that path still refuse, under a headline that names
  which leg failed (`is NOT ANY COMMITTED VERSION of …`) and states the window it searched. A
  copy older than the window is refused, never assumed.
- Unchanged: a copy in no checkout at all, a `source_path` absent from the ref, a manifest that
  does not parse, a row naming another repo, a failed git call, a failed fetch on an otherwise
  clean copy, `KTP_FRESHNESS_OFFLINE`, and `KTP_FRESHNESS_BYPASS` printing its whole refusal.
- **Not widened to the non-installed path.** A copy running from a drifted checkout still
  refuses, including when its bytes are an older committed blob — exactly the shape now accepted
  when installed. That is the shared-checkout hazard, where refreshing *is* the available fix,
  and `test_a_checkout_copy_that_is_merely_behind_is_still_refused` holds the boundary.
- Tests in `tests/unit/test_fleet_script_freshness.py`. The two cases that asserted the old
  refusal now assert the acceptance; the control for over-reach is a copy whose md5 matches its
  row and whose bytes match no commit of the path, which refuses before and after the change.
