### `scripts`: `ktp-install` carries a file's owner across the swap, not just its mode (2026-10-12)

An install is an atomic rename of a newly written `.new` file, so the installed file is a new
inode owned by whoever ran the install. `install()` re-applied the old file's **mode** and
nothing else, which is the dangerous half of the pair: a `750` file owned by a service account
came back `root:root` with its mode intact, and `750` then gave that account nothing at all.

- **Measured instance.** `/opt/ktp-corpus-push/push-corpus.py` was installed 2026-10-10 as
  `-rwxr-x--- root root` while `ktp-corpus-push.service` and `ktp-corpus-push-denver.service`
  both declare `User=corpuspush`. Python died `[Errno 13] Permission denied` before any upload,
  so both corpus mirror pushes failed on their next tick. Every other file in that directory is
  `corpuspush:corpuspush`; only the installed one was root-owned. The bytes were correct — this
  was never a content problem, which is why `ktp-install --report` read `OK` throughout.
- **The fix** captures `st_uid`/`st_gid` beside the mode and `os.chown()`s the temp file before
  the rename, skipping the call when the ids are already the installing process's (the ordinary
  root-installs-a-root-file case, so nothing changes there). A chown that cannot be performed
  **refuses before the swap** rather than installing a file its own service cannot read — the
  same shape as every other check in that function, which ends at a verified state or a refusal.
- **Deliberately out of scope:** a *fresh* install to a path that does not exist yet still lands
  on the installing user, because there is no prior owner to carry. No instance of that has been
  measured, and the honest fix for it is an explicit `--owner`, not a guess.
- **Tests.** One test sets a foreign uid/gid on the destination and asserts both survive the
  upgrade along with the mode; it takes its ids from `pwd` as root and from a supplementary group
  unprivileged, since the defect lands on the installer's ids either way. Reverting only
  `scripts/ktp-install` to its previous bytes reddens exactly that test (`0 != 1` — uid came back
  root) and nothing else. A second test is labelled a regression guard rather than evidence: it
  pins that the preserve step does not fire on a fresh install.
