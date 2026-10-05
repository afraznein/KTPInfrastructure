### `scripts`: the install-freshness check fetches the deploy checkout instead of keeping its own mirror (2026-10-03)

`ktp-install-freshness.sh` compares installed files with `origin/main`, and the
open question was how that ref stays current when `/opt/ktp-infra` is never
auto-pulled. The operator ruled for fetch-only: the check runs `git fetch` in
`/opt/ktp-infra` and compares against the fetched ref, leaving the working tree
alone. That replaces the bare mirror the first version required, which the
script used to create nowhere and the runbook asked a person to clone by hand.

The fetch is `git fetch --no-tags --refmap= origin +refs/heads/main:refs/remotes/origin/main`.
The explicit refspec writes one remote-tracking ref. `--refmap=` matters as
well: without it git also applies the configured refspec to whatever it fetched,
so a checkout whose `remote.origin.fetch` had been set to write `refs/heads/*`
would have had its local `main` moved. A test sets up exactly that config, and
it fails without the flag. The script records HEAD before the fetch and exits 1
if it moved. `AGAINST_REF` has to be `<remote>/<branch>` now, because a fetch
never refreshes a local ref, so a check against one would read as fresh forever.

Side effect: newly merged commits are present in `/opt/ktp-infra` after each
run, so `ktp-install --commit <new sha>` works there without anyone moving the
tree.

Tests: `tests/unit/test_install_freshness_fetch_only.py` runs the real script
against a throwaway upstream and a clone with a hand edit and an untracked file.
Against `origin/main`'s script 5 of the 8 fail (heads refspec moved `main`,
`/opt/ktp-infra` refused, three bad refs accepted); on this branch all 8 pass.
Still not installed or enabled; `docs/runbooks/INSTALL_FRESHNESS.md` has the steps.
