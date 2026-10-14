### `scripts` + `docs`: the stale-source refusal names a route, not a path (2026-10-13)

`ktp-install`'s refusal was right and its advice was wrong. It ended *"Install from
`/opt/ktp-reports/KTPInfrastructure`, which tracks origin/main"* — and that tree does
not. Measured the day the guard went live: it sat at `f6c4aa0`, **21 commits behind**
real `origin/main`, with `FETCH_HEAD` eight days old, reporting `behind=0` because the
count was taken against its own stale ref. Its own `ktp-install` carried no guard, so
following the advice reinstalled a pre-guard tool.

**Naming any on-box path is the defect.** Nothing on that host pulls any checkout, so
every one of them goes stale and any path written into the message rots. The refusal now
names the route instead: `--file` with `--source-repo`, `--commit` and `--blob-md5`,
which takes the bytes from a staged file and needs no checkout on the box at all. It also
says what a checkout would have to be — *at* `origin/main` — rather than claiming some
directory is.

The two hardcoded figures are gone for the same reason. *"304 commits behind while
reporting 22"* was true for about a day: once the install-freshness unit's fetch refreshed
that checkout's `origin/main`, it began reporting **313** honestly. The property is what
holds; the numbers only ever mislead.

`docs/runbooks/INSTALL_FRESHNESS.md` had the same defect twice over, and worse, because its
steps were copy-pasteable:

- steps 1 and 2 were literally `ktp-install --repo /opt/ktp-infra …`, which the guard now
  **refuses** — the runbook told you to run the one command that cannot work. They now use
  the `--file` route, with a note on where to get the sha and the blob md5 (off-box).
- its prose claimed the fetch *"means a newly merged commit is present there to install
  from"*. The fetch moves only `origin/main`; HEAD, and therefore every byte in the working
  tree, stays put. It now says **compare against**, with the distinction spelled out.

**One finding from the test, which is the part worth keeping.** The first assertion was
`"--blob-md5" in p.stderr` — and it **could not fail**. `ap.error()` prints argparse's usage
line, which lists every flag, so the assertion passed with the guidance deleted entirely. A
mutation test caught it; reading it did not. It now keys on message-only wording, and both
directions are mutation-checked: reintroducing the reports-checkout path fails the
regression assertion, and deleting the guidance sentence fails the route assertion. 56
passed, 1 skipped, and the script restored byte-identical after both mutations.
