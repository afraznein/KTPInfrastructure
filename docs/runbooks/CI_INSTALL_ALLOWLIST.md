# CI install allowlist — CI keeps named scripts current, and nothing else

**Ruled 2026-11-02 (operator):** CI gets write access to the production script directory,
but only through an allowlist of named scripts, never the whole directory. This page
is the design, what it does and does not grant, and the operator steps to switch it on.

| piece | file |
|---|---|
| the scope | `config/ci-install-allowlist.tsv` |
| what enforces it | `config/sudoers.d/ktp-ci-install`, generated from the allowlist |
| the only privileged program | `scripts/ktp-ci-install`, installed at `/usr/local/sbin/ktp-ci-install` |
| the job | `.github/workflows/ci-install.yml` |
| the tests | `tests/unit/test_ktp_ci_install.py` |

## ⚠️ Read this first: the existing runner already runs as root

Measured read-only on the data server 2026-11-10:
`systemctl show actions.runner.afraznein-KTPInfrastructure.ktp-tier2-neindataatl.service -p User`
answers `User=root`, and `Runner.Listener` runs as root. `report-regeneration.yml` and
`fleet-audit.yml` already say so. **Any job on the `ktp-tier2` runner can write all of
`/usr/local/bin` today, with no allowlist at all.**

So an allowlist enforced by sudo only means something on a runner that is NOT root,
because root never asks sudo. That is why this workflow:

- runs on its **own** runner, as an unprivileged user `ktp-ci`, label `ktp-ci-install`;
- refuses to run at all when `id -u` is 0, so it cannot fall back to the root runner
  and quietly turn the allowlist into decoration;
- never triggers on `pull_request`.

This design does not shrink what the root runner can do. It makes sure the install
path does not inherit it.

## What the `ktp-ci` user can and cannot do

| | can | cannot |
|---|---|---|
| write `/usr/local/bin` directly | — | ✗ (root:root 755) |
| run anything as root | exactly one command per allowlisted path: `/usr/local/sbin/ktp-ci-install --install <that path>` | any other command, any other path, any extra argument (sudo matches the whole line; there is no wildcard in the file) |
| choose the bytes installed | — | ✗ the wrapper fetches `main` into its own root-only mirror and proves it is GitHub's tip with `ls-remote`; the job's checkout is never read |
| choose the commit | — | ✗ always the verified tip of `main` |
| widen the allowlist | — | ✗ a new row needs a merged PR **and** the operator reinstalling the sudoers fragment |
| overwrite a hand edit | — | ✗ DRIFT is refused; only a file whose bytes still equal its last manifest row is replaced |
| install a script for the first time | — | ✗ NOT-RECORDED is refused; the first install is a person's |
| install the installer, the wrapper, or a watcher | — | ✗ `ktp-install`, `ktp-ci-install`, `ktp-install-freshness.sh`, `ktp-tier2-heartbeat.sh`, `ktp-tier2-stack-drift.py` are refused in code, even if listed |
| read the manifest and the installed files | ✓ (`DEPLOYED.tsv` is 644; all recorded `KTPInfrastructure` paths were readable as uid 65534 when measured) | |

So the worst a compromised job on that runner can do is install, early, the bytes `main`
already holds, for a path the allowlist already names. That is what a merge to `main`
is meant to cause anyway.

## What happens on a refusal

Nothing is written. The install step goes red naming the path and the reason, the
allowlisted check goes red, and the file stays exactly as it was, which leaves it a
person's install. The daily `ktp-install-freshness` unit keeps reporting it STALE, so a
refusal cannot go quiet.

| refusal | meaning | what clears it |
|---|---|---|
| `NOT-ALLOWLISTED` | not on the list at `main` | a PR adding the row, plus the sudoers reinstall below |
| `NOT-RECORDED` | no manifest row | a person installs it once with `ktp-install`, or records it with `--record-only` |
| `DRIFT` | someone edited the live file | a person decides: fold the edit into the repo, or reinstall over it |
| `SOURCE-GONE` | `main` no longer has the source | retire the live file and remove the row |
| `OTHER-REPO`, `SOURCE-MISMATCH` | the row says the file came from elsewhere | fix the row or the allowlist; never guess |
| `NOT-REGULAR` | a symlink or not a file | a person looks |
| sudo refuses | the sudoers fragment on the box is older than the allowlist | reinstall the fragment |

## The loud half: `outside-list`

A second job checks every `KTPInfrastructure` row in the manifest that is NOT
allowlisted, and fails when one is:

- **STALE-OUTSIDE-LIST** — behind `main`, and CI may not install it, so a person owes it;
- **REMOVED-UPSTREAM** — its source is gone from `main`. An allowlist on its own is blind
  to deletions, so without this a script deleted upstream would stay on the box forever.

It is a separate job so that "a person owes an install" never reads as "the installer
broke". Expect it to be red until the existing stale rows are installed by hand: that red
is the backlog, stated.

## Triggers

Push to `main`, and manual dispatch to re-run after a refusal is cleared. Not
dispatch-only: an installer that needs a person to remember it is the drift this
replaces. No `paths:` filter, because the outside-list job reports on the whole recorded
estate. Never `pull_request`.

## Operator steps to switch it on

All as root on the data server. None of this is done by the PR.

1. **Create the user.**
   `useradd --system --create-home --home-dir /opt/ktp-ci-runner --shell /usr/sbin/nologin ktp-ci`
2. **Register a second runner as that user**, in `/opt/ktp-ci-runner/actions-runner`, with
   the extra label `ktp-ci-install`, and install its service with
   `./svc.sh install ktp-ci`. Confirm with
   `systemctl show actions.runner.*ktp-ci* -p User` → `User=ktp-ci`.
   Do not add `ktp-ci` to any group that can write `/usr/local`, `/etc` or `/opt`.
3. **Install the wrapper with `ktp-install`**, so it has a manifest row (stage the blob at
   the merge commit, then):
   `ktp-install --file <staged> --source-repo KTPInfrastructure --commit <sha> --src scripts/ktp-ci-install --dest /usr/local/sbin/ktp-ci-install --expect-md5 - --blob-md5 <md5 of the blob>`
   It must be root-owned and not group/world-writable; the wrapper refuses to run otherwise.
4. **Install the sudoers fragment, checked first:**
   ```bash
   visudo -cf <staged copy of config/sudoers.d/ktp-ci-install>
   install -m 0440 -o root -g root <staged copy> /etc/sudoers.d/ktp-ci-install
   visudo -c
   ```
5. **Verify least privilege, both directions:**
   ```bash
   sudo -l -U ktp-ci
   ```
   must list exactly one `(root) NOPASSWD: /usr/local/sbin/ktp-ci-install --install /usr/local/bin/<name>`
   line per allowlist row and nothing else. Then the controls:
   ```bash
   sudo -u ktp-ci sudo -n -l /usr/local/sbin/ktp-ci-install --install /usr/local/bin/ktp-spike-digest   # prints the command: allowed
   sudo -u ktp-ci sudo -n -l /usr/local/sbin/ktp-ci-install --install /usr/local/bin/ktp-install         # refused
   sudo -u ktp-ci sudo -n -l /usr/local/sbin/ktp-ci-install --install /usr/local/bin/ktp-spike-digest x # refused
   sudo -u ktp-ci sudo -n -l /bin/sh                                                                     # refused
   sudo -u ktp-ci touch /usr/local/bin/zqwbw1110-probe                                                   # Permission denied
   ```
   `sudo -l <command>` only answers whether sudo would allow it; it runs nothing.
6. **Every allowlisted path must already have a manifest row.** Check with
   `ktp-ci-install --check --scope allowlisted --repo <a checkout at main> --ref <sha>`;
   a `NOT-RECORDED` row needs `ktp-install --record-only` (if the file is current) or a
   normal install first.
7. **Dispatch the workflow once** and read both jobs.

**Stop switch:** `touch /etc/ktp/ci-install.disabled` makes every install refuse, without
touching sudoers or the runner. Remove the file to resume.

**Adding a script later:** a PR adds the row and the regenerated fragment
(`scripts/ktp-ci-install --emit-sudoers --repo . --ref HEAD > config/sudoers.d/ktp-ci-install`;
a test fails if they disagree). After it merges, repeat step 4. Until then sudo refuses
the new path and the install job is red, which is the intended order: CI cannot grant
itself a path.
