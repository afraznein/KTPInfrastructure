### Added
- `scripts/check-live-script-inventory.py` holds `docs/LIVE_SCRIPT_INVENTORY.md` to the repo it points
  at, wired unconditionally into `config-tests.yml`. Nothing read that inventory before:
  `git grep -l LIVE_SCRIPT_INVENTORY -- tests/ .github/ scripts/` returned zero against a positive
  control of 130 `def main` hits under `scripts/`, and the only references anywhere were prose. An
  unvalidated record of what is installed on a production box does not go quiet when it rots, it gets
  cited — `changelog.d/2026-10-07-health-capture-per-half-leg.md` cited the
  `ktp-data-server-health.sh` row as the live revision five weeks after two separate installs of that
  script had landed on the box.

  Each row makes two claims, and only one is decidable from a checkout: that the recorded md5 is the
  blob at `<repo>:<path>@<commit>` (checkable), and that the file on the host has that md5 (not
  checkable here, ever). The script asserts the first and refuses to imply the second — every run
  prints how many live claims it verified, which is zero unless an `md5sum`-format file read off a
  host is passed as `--live-md5`. Rows sourced from another repo, from upstream software, or from an
  installer with no blob to equal are listed under a `NOT DECIDABLE FROM THIS REPO` header and
  counted; the classified counts must sum to the parsed row count or the run exits 2, because a check
  that silently skips what it cannot test is the defect it exists to catch.

  Exit codes follow `check-archive-lift.py`: `0` every repo claim verifies, `1` a repo claim is false
  or a `SUPERSEDED` / `UNVERIFIABLE-PIN` marker is missing or stale, `2` the check could not trust
  itself — doc missing, no row parsed, a candidate line the grammar rejected, no row hard-verifiable,
  or a shallow clone, which cannot answer reachability at all. `--selftest` builds fifteen document
  fixtures plus both directions of the live-manifest leg, from commits derived out of the repo at run
  time, and runs ahead of the real check in CI.

### Changed
- `docs/LIVE_SCRIPT_INVENTORY.md` rows whose source path has changed in this repo since their pinned
  commit now carry a `SUPERSEDED` token. A row is a dated measurement, so the repo moving on does not
  make it false — it makes it mute, and the doc gave a reader no way to tell a row that still
  describes the repo tip from one the repo passed weeks ago. The checker asserts the token in both
  directions: missing on an overtaken row fails, and present on a row whose pin is still current fails
  too, which is what stops the token becoming a permanent silencer the first time someone re-pins a
  row. Every `MATCH` row's recorded md5 was verified against its own pinned blob in the process and
  not one was wrong, so the markers record staleness, not error. `--warn-superseded` downgrades that
  leg to advisory if it proves noisier than it is worth.

  `/usr/local/bin/ktp-data-server-health.sh` is the row that prompted this and the only one annotated
  individually: its pin has no `ktp-hitreg-reg` marker where `main` has two, and
  `andsmit9/ktp-coordination`'s `NEIN-DEPLOY.md` records that file installed under `/usr/local/bin/`
  twice after the inventory was taken (`dpl-41f8`, `dpl-9f25`). Re-pinning it needs `md5sum` on the
  box; a newer-looking commit guessed from here would restate the same defect with fresher numbers.

- Three rows pin a commit that is **not an ancestor of `main`**, so nobody who clones this repo can
  check them: `cf93488405` and `63b45b20cc` are reachable from no ref, and `471aab1c59` sits on an
  unmerged feature branch. They carry `UNVERIFIABLE-PIN`, and the checker gates on it unconditionally —
  `--warn-superseded` deliberately does not cover this leg, because a pin nobody can reach is a
  provenance hole rather than noise. Found by the checker's first CI run, where an `actions/checkout`
  working tree could not resolve `cf93488405` at all: the workstation that wrote these rows still held
  the dangling objects, so a local run saw nothing wrong. Reachability (`merge-base --is-ancestor`), not
  object presence, is therefore the test — it answers the same in a fresh clone as in a long-lived one —
  and a shallow clone exits 2 up front rather than reporting per-row verdicts it cannot stand behind.
