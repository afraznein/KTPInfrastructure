### `scripts`, `ci`: CI installs allowlisted scripts from verified main, and refuses everything else (2026-11-10)

Ruled 2026-11-02: CI may write the production script directory only through a named
allowlist. `config/ci-install-allowlist.tsv` is that list. `scripts/ktp-ci-install`,
installed at `/usr/local/sbin`, is the only privileged program, and
`config/sudoers.d/ktp-ci-install` (generated from the list, one exact command per
row, no wildcard) is the only grant. The wrapper fetches `main` into its own root-only
mirror, checks it against GitHub's tip, reads the allowlist and the bytes from there,
and replaces a file only when its bytes still equal its last manifest row. It refuses
anything off the list, unrecorded, hand-edited, symlinked or removed upstream, and
never installs the installer or a watcher.

`.github/workflows/ci-install.yml` runs it on push to `main` and on dispatch, on a
separate unprivileged runner (`ktp-ci`, label `ktp-ci-install`), and refuses uid 0:
the existing `ktp-tier2` runner runs as root, and root never asks sudo, so an
allowlist there would enforce nothing. A second job fails on every recorded script
off the list that is stale or whose source left `main`, because an allowlist alone
cannot see either.

Nothing here is live until the operator steps in
`docs/runbooks/CI_INSTALL_ALLOWLIST.md` are done. Every refusal in the tests is
paired with a control that the same file installs once that one condition is lifted,
and removing any single guard turns at least one test red.
