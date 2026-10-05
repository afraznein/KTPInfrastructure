### `scripts`: the corpus offsite leg also carries the AC weapon-context sidecars (2026-10-05)

`/opt/ktp-ac-api/weapon-context` had no copy anywhere. Once the nightly sweep
deletes a session's weapon-switch rows, its sidecar is the only record of which
weapon was in hand, and neither the corpus leg (bundles only) nor
`ktp-backup.sh` looked at it. Per the operator's 2026-10-05 ruling it now leaves
through the corpus leg: same `age` recipients, same Sunday 06:00 run, unbounded
retention.

- **Its own far-side prefix**, `<corpus dir>/weapon-context/`, with objects at
  `objects/<sha256-of-plaintext>.age`, a current-version manifest beside them
  and dated manifests under `manifests/`. Bundle objects and the bundle manifest
  are where they were, so the two populations never mix.
- **A rewrite is a new object, and the old one stays.** Sidecars are rewritten
  in place when a later hydrate is more complete. The stable manifest names the
  current version of every file, so a restore takes the latest; the dated
  manifests map the older versions.
- **Hashed from a snapshot.** The sidecars are copied into the work dir before
  they are hashed, so a rewrite mid-run cannot put one version's ciphertext
  under another's name.
- **Strict selection, empty refused.** Only `<shard>/<session>.weapons.json` is
  copied, the in-flight `tmp/` never, anything else is counted in a warning, and
  a missing or empty store fails the run before anything ships.
- **Manifests are verified on the far side by content**, and ship with
  `--ignore-times`: two runs in the same second wrote a same-size manifest with
  the same mtime and rsync kept the stale one. The tests found it; weekly runs
  never would have.
- `ktp-corpus-restore.sh --set weapon-context` restores the sidecars;
  `ktp-corpus-drill.sh` round-trips them, rewriting one in place between two runs.
- The bundle log line now reports distinct objects next to the bundle count,
  which `docs/BACKUP_SCOPE.md` had flagged as wrong whenever bundles collapse.
- `ktp-corpus-offsite.sh` is now executable in git; the drill refuses a
  non-executable offsite script, so a fresh checkout could not run it.
