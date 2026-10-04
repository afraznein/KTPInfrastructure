# Deploy manifest

Every script we install on a live host is recorded in a manifest on that host:
which file, its md5, and the repo commit it came from. There is no version string
inside the scripts. A hand-bumped label goes stale the first time someone forgets
to bump it, while the bytes cannot, so the installed file stays byte-identical to
its git blob and the manifest says which blob.

## Where it lives

One format, two places, so no host needs sudo to record an install:

| who installs | manifest |
|---|---|
| root (data server, `/usr/local/bin`, `/etc/...`) | `/usr/local/share/ktp-infra/DEPLOYED.tsv` |
| any other user (`dodserver` on the game hosts) | `~/.ktp/DEPLOYED.tsv` |

`KTP_MANIFEST` overrides both. The file is append-only: a header line, then one
row per install. A path's current state is its **last** row.

```
installed_path  md5  source_repo  source_commit  source_path  deployed_at_iso  previous_md5  deployed_by
```

Tab-separated. `source_commit` is the full 40-hex sha. `previous_md5` is what
was there before, or `-` for a new file.

## Installing: `scripts/ktp-install`

Where the repo is checked out (the data server's `/opt/ktp-infra`, after a
deliberate `git fetch`):

```bash
ktp-install --repo /opt/ktp-infra --commit <sha> --src scripts/hltv-restart-all.sh \
            --dest /usr/local/bin/hltv-restart-all.sh --expect-md5 <md5 there now>
```

Where there is no checkout (the game hosts), push the bytes first and vouch for
them with the blob's md5, taken where the repo is:

```bash
git show <sha>:monitoring/fleet-health/ktp-fleet-health.sh | md5sum     # on the workstation
ktp-install --file ~/ktp-fleet-health.sh.push --source-repo KTPInfrastructure \
            --commit <full sha> --src monitoring/fleet-health/ktp-fleet-health.sh \
            --blob-md5 <that md5> --dest ~/ktp-fleet-health.sh --expect-md5 <md5 there now>
```

A filled template (`ktp-scheduled-restart.sh`, `hltv-api.py`, `ktp-backup.sh`)
cannot equal any blob, because the filling is the point. Install it with
`--template`, naming the `.example` it was filled from; the row records the
template's commit and path and the filled file's md5:

```bash
ktp-install --file ~/ktp-scheduled-restart.sh.filled --template --source-repo KTPInfrastructure \
            --commit <full sha> --src scripts/ktp-scheduled-restart.sh.example \
            --dest ~/ktp-scheduled-restart.sh --expect-md5 <md5 there now>
```

What it does, in order, and why each step is there:

- **Refuses unless the destination's md5 is `--expect-md5`** (`-` for a new file).
  An install is a compare-and-swap, so a hand edit made since you last looked is
  never overwritten silently.
- **Refuses a no-op** when the destination already has the new bytes.
- **Banks the outgoing file** in `/var/backups/ktp-install/` (root) or
  `~/.ktp/backups/` (others), named with its md5, and checks the copy. Never
  inside a docroot.
- **Writes `<dest>.new`, checks its md5, then `mv`s it over**, keeping the old
  file's mode, and reads the result back.
- **Appends the manifest row** under a file lock, and refuses to append under a
  header it does not recognise.

## Recording what is already right: `ktp-install --record-only`

An install is a copy, so it refuses a no-op. That guard is correct and it left
one state unreachable: a file that is **already the right bytes but was never
recorded** could not be recorded, because the only way into the manifest was
through a copy that would not happen. `--report` went on indicting it and
nothing could clear it.

```bash
ktp-install --record-only --repo /opt/ktp-infra             --commit <sha> --src scripts/foo.sh --dest /usr/local/bin/foo.sh
```

It hashes what is on disk, resolves the blob at that commit, and appends the row
**only if they are equal**. It writes no file, banks no backup and changes no
mode. It refuses: bytes that are not that blob; no `--repo` (without the blob
here the row would be your word rather than a check); `--template` (a filled
template cannot equal any blob, so there is nothing to verify against); `--file`,
`--blob-md5` or `--mode` (each names something other than the file being
recorded); a missing file; an `--expect-md5` that does not match; a duplicate of
the path's existing last row; and a manifest that does not parse.

A recorded row carries `previous_md5` **equal to** `md5`. The install path
refuses a no-op, so it can never write one — that is how a recorded row is told
from an installed one, with no new column.

⚠️ **Recording says which blob these bytes are, not that they are the newest.**
Record an old commit and `--against-ref` still reports `STALE`. The row is
honest; the file is still behind.

## Checking: `ktp-install --report`

Reads every manifest that applies on the host and compares each recorded path's
current md5 to its last row.

| state | meaning | exit |
|---|---|---|
| `OK` | bytes match the last row | 0 |
| `TEMPLATED` | a filled template, bytes match the last row | 0 |
| `DRIFT` | the file changed since it was recorded | 1 |
| `MISSING` | the file is gone | 1 |
| `SOURCE-MISMATCH` | with `--repo`: the recorded commit does not hold those bytes | 1 |
| `UNTRUSTED` | no manifest, an empty one, or one that does not parse | 2 |

It fails closed: a manifest that cannot be read proves nothing, so it is never
reported as clean.

⚠️ **A clean report covers only what has been recorded.** A script installed by
hand, without `ktp-install`, is in no manifest and is invisible to `--report`.
`docs/LIVE_SCRIPT_INVENTORY.md` lists what is live and not yet recorded.

## Freshness: `ktp-install --report --repo DIR --against-ref REF`

🔴 **The table above answers "untouched since install", not "current".** They read
identically -- both print `OK` -- and only one of them is the question anybody
means. A file nobody has edited reports `OK` forever while the repo merges past
it, because the bytes still match the row and the *row* is what went stale. That
is how the Tier 2 stack-drift checker ran superseded logic for weeks with this
report calling it healthy, and it is the ordinary state of `/usr/local/bin`:
nothing installs these files, a person copies them.

`--against-ref` resolves each row's `source_path` at REF and compares the
**installed bytes** to what REF holds.

| state | meaning | exit |
|---|---|---|
| `CURRENT` | the installed bytes are REF's bytes | 0 |
| `STALE` | untouched since install, and REF has moved past it | 1 |
| `SOURCE-GONE` | REF no longer holds that `source_path` (renamed or deleted) | 1 |
| `OTHER-REPO` | the row names a different `source_repo`; not compared | 0 |

`DRIFT` and `MISSING` outrank freshness -- a file edited in place is reported as
edited, not as stale. A ref that does not resolve, or `--against-ref` without
`--repo`, is `UNTRUSTED` (2): a freshness check that could not run must not read
as fresh.

⚠️ **A shallow clone cannot answer the provenance leg.** `--repo` also re-checks
each row against its *recorded* commit, and a commit the checkout does not carry
is noted rather than counted -- `actions/checkout` is shallow by default, so
treating "I do not have that commit" as a mismatch would fail every run for the
wrong reason. Use `fetch-depth: 0` when you want the provenance leg to mean
something.

**This is the destination-side twin of `scripts/ktp_script_freshness.py`.** That
one refuses to touch the fleet *from* a checkout behind `origin/main`; this one
asks whether what is already installed *on* a host equals `origin/main`. Neither
sees the other's failure, and both exist because a rule applied from memory is a
rule applied sometimes.

`ktp-verify-deploy` imports `ktp_script_freshness` at module level, so the two install together.
Installed alone, a verifier that gave a wrong answer becomes one that gives none: it fails at import,
before `main()` runs.

Installed, the guard reads this manifest. A copy outside any checkout is current when its bytes have the
md5 of its last row **and** equal the blob at the fetched `origin/main` for that row's `source_path`, in
`KTP_FRESHNESS_REPO` (default `/opt/ktp-infra`). Install the script with `ktp-install`, never `cp`, or
the verifier refuses every run with "no deploy manifest records it"; install the guard module beside it
from the same commit, since an older guard has no installed-copy rule at all.
