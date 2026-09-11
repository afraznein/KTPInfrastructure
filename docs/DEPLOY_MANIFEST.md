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
