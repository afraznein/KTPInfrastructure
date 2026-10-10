# Runbook: one shared `stage-wave.py` on the data server

**Status: PROPOSAL.** Nothing described under [Install](#install) exists on any
host yet. The code half (`scripts/ktp-deploy.py`, the ledger and credential
changes) ships with this document; the host half is the operator's to run, after
the decisions in [Operator decisions](#operator-decisions) are made.

**Measured 2026-10-03**, read-only, from the operator workstation.

## Why

`stage-wave.py` is the way plugins, modules and the engine reach the fleet. It
carries every gate the manual process used to depend on someone remembering:
the attribution gate, md5 pins, the build base, `--pull-live` rollback copies,
and the row-flip gate fed by the wave ledger.

It was written for one person on one workstation. At least three people deploy
to the fleet, and the HUD-observer plugin has twice been deployed around it. The
answer is not to ask harder. It is to give everyone a copy they can run that
keeps the gates intact and keeps one record.

## What was measured

### The data server

- **Human login accounts:** `root` (keys only), `krodssh` (stats collaborator),
  `cadaver` (HUD-observer maintainer). `ftpuser` and `hltvserver` also have
  shells. **No deploy group exists.**
- **Both collaborator accounts already hold unrestricted sudo** on the data
  server. Both grants were deliberate operator decisions. So on this box, file
  permissions can keep a credential away from service accounts. They cannot
  keep it away from either deployer, and they cannot keep it away from the
  tier-2 CI runner, which runs as `root`. Read every "group-readable" below
  with that in mind.
- **The fleet SSH credential is already on the box in several root-only
  places:** a dotfile in root's home, the fleet-audit JSON, the profile
  aggregator's `.env`. Root also holds two keys that `dodserver` accepts on
  all five game hosts, with no `from=` restriction.
- **`/opt/ktp-infra`** is a root-owned checkout, detached, current with
  `origin/main` when measured. It is never auto-pulled, on purpose.
- **Toolchain:** Python 3.12, paramiko 2.12, git 2.43. Nothing extra is needed.
- **No wave-sweep unit is installed**, and `/etc/ktp/wave-sweep.env` does not exist.

### The game hosts

- `dodserver` accepts password **and** key auth on all five.
- `cadaver` exists on all five with unrestricted sudo, key auth. `krodssh` exists
  on none.

### How the HUD-observer plugin was deployed on 2026-09-29

From the maintainer's own machine, as `cadaver`, on each game host in turn:
`sudo install` of the `.amxx` **over the live file** (not a `.new`), an md5
check, then `sudo -u dodserver ./dodserverN restart` for each instance, mid-day.
The data-server backend was changed the same evening through `sudo` as well.

That skipped every gate: no attribution check, no `--pull-live` (the outgoing
build exists nowhere we hold), no ledger entry, an activation outside the 03:00
swap, and a restart of live instances. Nothing here suggests bad intent. The
direct path was the only one he had.

### The ledger and the rows

- The only wave ledger is on the operator workstation. It is complete and
  every entry has been reconciled.
- The version rows (`fleet-versions` `SKILL.md`) exist only on the workstation,
  in a directory that is not a git repo and has no remote.

## What breaks when several people run it

Each of these fails **silently**, which is the reason for the wrapper rather than
a paragraph of instructions.

| # | Assumption in today's code | What happens with several users on one box |
|---|---|---|
| 1 | Ledger defaults to `~/.ktp/waves` | One ledger per home. The row-flip gate only sees your own waves, and `reconcile` is blind to everyone else's. |
| 2 | Rows default to `../../.claude/skills/fleet-versions/SKILL.md` from the checkout | Not on the box. The gate is *inconclusive*, which is fatal: nobody can stage. |
| 3 | Credential from env or `~/.ktp_fleet_ssh_password`, password only | Every person needs their own copy of one shared password. Nothing on the game hosts can tell them apart. |
| 4 | Nothing serialises stages | The attribution gate is check-then-act. Two people staging at once both see a clean fleet and then both stage. That is the stacked activation the gate exists to prevent. |
| 5 | Wave id: `while exists(id): id += 1`, then `open(w)` | Two stagers in one directory pick the same id, and the second overwrites the first's unreconciled wave. **Fixed here** (atomic `os.link`). |
| 6 | Entries record no person | A blocked stager cannot tell whose wave blocks them. **Fixed here** (`staged_by`, `reconciled_actor`). |
| 7 | The freshness guard runs `git fetch` in the checkout | git refuses a repo owned by another user ("dubious ownership"), and a read-only `.git` cannot fetch. Either way the guard refuses, correctly, every time. |
| 8 | `--pull-live DIR` is optional, and `DIR` is wherever you are | Rollback copies end up scattered across home directories, or never get made at all. |
| 9 | The row-flip gate is global | One person's unflipped row blocks the **next person's** stage. That is intended, but it now crosses people, so everyone must be able to flip a row. |
| 10 | paramiko's defaults try the agent and `~/.ssh` before the password | As root on this box, a wrong or empty password still connects through root's keys. A check that should fail passes instead. The new key path turns the fallback off. |
| 11 | `ktp-verify-deploy.py` (the morning-after check) reads only a password | It is not wrapped yet. Key-only users cannot run it. Follow-up. |

## The design

### Layout

```
/opt/ktp-deploy/KTPInfrastructure   clone of origin/main, group ktp-deploy, setgid,
                                     core.sharedRepository=group. Never edited by hand.
/usr/local/bin/ktp-deploy           symlink -> the clone's scripts/ktp-deploy.py
/var/lib/ktp-deploy/                root:ktp-deploy 2775
    waves/                          THE wave ledger (canonical)
    rollback/                       --pull-live copies, one dir per stage
    fleet-versions.md               THE version rows (see "Where the rows live")
    stage.lock, stage.lock.holder   one stage or ledger write at a time
    audit.log                       one JSON line per run: who, commit, argv, exit code
/etc/ktp-deploy/fleet-ssh-password  root:ktp-deploy 0640 -- only if the shared-password option is chosen
~<user>/.ssh/ktp_deploy_ed25519     per-person dodserver key -- if the per-key option is chosen
```

### What `ktp-deploy` does on every run

1. Refuses before doing anything if the rows file is missing or no credential
   can be found. "Could not look" never passes.
2. Takes `stage.lock` without waiting. A second person is told who holds it
   rather than queued, because waiting out someone else's wave and then staging
   on top of it is exactly the stack the gate is there to stop.
3. Brings the clone to `origin/main` with the wave sweep's own `prepare_tree()`:
   fetch, refuse if a tracked file was edited (and keep the edit), check out
   detached, then assert `HEAD` and `scripts/` match. So the shared copy is
   re-verified on every run and never hand-edited.
4. Runs `stage-wave.py` or `ktp-wave-ledger.py` **from that clone**. The
   freshness guard inside it therefore checks a real checkout, and
   `KTP_FRESHNESS_BYPASS/_OFFLINE/_REPO/_REF` are stripped from its environment.
   git's ownership check is satisfied with `safe.directory` passed as command-scope
   config, which that check accepts, so no `/etc/gitconfig` change is needed.
5. Points the child at the shared ledger and rows, and sets `KTP_DEPLOY_ACTOR`:
   the `sudo` user or the login name. A caller can set it explicitly only when
   running as root. Every wave entry then carries `staged_by`.
6. For `stage`, adds `--pull-live /var/lib/ktp-deploy/rollback/<UTC>-<actor>`
   unless the caller passed `--pull-live`, `--dry-run` or `--preflight-only`, or
   `--no-pull-live`. That last one is for a first-ever deploy, where there is no
   live copy and `--pull-live` is fatal.
7. Writes `umask 002` files, so the next deployer can still reconcile a wave
   this one recorded.
8. Appends one line to `audit.log`. It never records a secret; a test asserts that.

### The fleet credential: two options

**Option A: shared password, group-readable.** Copy the existing `dodserver`
password into `/etc/ktp-deploy/fleet-ssh-password` (`root:ktp-deploy 0640`).
Nothing on the game hosts changes. Nobody gains access they do not already
have, because both deployers can already read the root-only copies through
`sudo`. The cost is that every stage authenticates as the same password, so
game-host logs cannot say who staged. Only the box's `audit.log` and the wave
ledger can. Revoking one person means rotating the password for everyone and
every service.

**Option B: one key per person (recommended).** Each deployer gets their own key
at `~/.ssh/ktp_deploy_ed25519` on the box. Its public half goes into
`~dodserver/.ssh/authorized_keys` on all five game hosts, prefixed with
`from="<data-server address>",no-port-forwarding,no-agent-forwarding,no-X11-forwarding`.
`KTP_FLEET_SSH_KEY` then selects only that key, with no agent, no `~/.ssh` scan
and no password fallback: `fleet_ssh_auth()`, used by all three connection
sites (`deploy-to-fleet.py`, `stage-wave.py`, the ledger's fleet read). The
game hosts' `auth.log` names the key fingerprint. One person is revoked by
deleting one line on five hosts. The `from=` means a copied key is no use off
the box.

Option B does not make the box a security boundary between deployers: either
of them can `sudo` into the other's home. What it buys is **attribution and
per-person revocation**, which is what a shared password can never give.

### The wave ledger: one canonical ledger, on the box

Making the box canonical is what turns three people into one record. To migrate:

1. Copy the workstation's `~/.ktp/waves/*.json` into `/var/lib/ktp-deploy/waves/`.
   They are all reconciled, so this is history and not state. Old entries have
   no `staged_by`; `status` prints `NOT RECORDED` for them rather than guessing.
2. 🔴 **SUPERSEDED BY THE D3 RULING BELOW — do not follow as written.** It said:
   stage only through `ktp-deploy` on the box, the operator included, because a
   stage from the workstation would write the workstation ledger and miss the
   lock. **D3 was ruled NO on 2026-10-05**: the operator keeps staging from his
   workstation. The hazard the sentence names is real and now unaddressed, so the
   workstation path has to reach the box's ledger and lock. See § Operator
   decisions.
3. Move the scheduled wave sweep to the box: the repo's `systemd/ktp-wave-sweep.service`
   with `KTP_CLAUDE_MD=/var/lib/ktp-deploy/fleet-versions.md` and
   `KTP_WAVE_LEDGER_DIR=/var/lib/ktp-deploy/waves`. Then retire the workstation
   task. Two sweeps against two ledgers would disagree about what is ledgered.

### Where the rows live

The row-flip gate reads one file, so that file has to be on the box and
writable by every deployer (risk 9). The gate needs very little from it: a
table row per component that contains the live md5.

- **Recommended: the box copy becomes the home of the rows**,
  `/var/lib/ktp-deploy/fleet-versions.md`, group-writable. The workstation skill
  keeps its narrative and traps, and points at the box for "what is live".
  A deployer flips their own row on the box in the same session as the
  morning-after verify. That is the only point at which the flip is cheap.
- *Alternative:* move the rows into a private repo and have the wrapper read
  `origin/main` of it. That gives history and review, but every flip becomes a
  commit plus push, and the box needs a read credential for a private repo.
- *Rejected:* syncing the workstation file to the box on a timer. That gives
  two copies of one fact, and the gate would read whichever one is staler.

### The HUD-observer plugin

The plugin stays externally maintained. We do not review it, and these gates
do not review it either. They check that a wave is clean to stage, that the
file is the one its author pinned, that the outgoing build is preserved, and
that the record moves with the fleet. In practice:

```bash
scp KTPHudObserver.amxx cadaver@<data server>:~/
ssh cadaver@<data server>
ktp-deploy stage -f ~/KTPHudObserver.amxx \
    --expect KTPHudObserver.amxx=<md5 he built> \
    --base   KTPHudObserver.amxx=JimmyLockhart65616/DoD-hud-observer@<sha>
# next morning, after the 03:00 swap:
ktp-deploy ledger reconcile          # then flip the KTPHudObserver row on the box
```

Two things change for him, and both are the operator's call. First, activation
is the 03:00 swap, not a mid-day restart. Second, his game-host sudo stays a
path that bypasses all of this until it is narrowed.

## Operator decisions

🔴 **These were RULED on 2026-10-05 and three went against the recommendation.
The ruling, not the Recommendation column, is what the install implements:**

| # | Ruled | Against the recommendation? |
|---|---|---|
| D1 | **Yes** — `krodssh` gets `dodserver` access as his own key. | no |
| D2 | **Yes** — per-person keys, not the shared password. | no |
| D3 | **NO** — the operator keeps staging from his workstation too; the box is not the only staging place. | **yes** |
| D4 | **Yes** — the version rows live on the box. | no |
| D5 | **NO** — mid-day HUD-observer restarts stay allowed, done carefully. | **yes** |
| D6 | **NO** — `cadaver` keeps his game-host sudo; no narrowing. | **yes** |
| D7 | **Yes** — both join `ktp-deploy`. | no |

⛔ **D3=NO with D4=YES is the one that changes the design, and the wave-ledger
section above is still written for D3=YES.** Read step 2 there — *"stage only
through `ktp-deploy` on the box"* — as superseded: following it either breaks the
operator's own path or reopens the two-ledger split this file exists to close.
➡️ **Resolve it before any install.** Either the workstation `stage-wave.py`
reads `/var/lib/ktp-deploy/fleet-versions.md` and writes `/var/lib/ktp-deploy/waves/`
over SSH — both are group-writable by `ktp-deploy` by design, which is the hook
that makes this possible — or the rows move to the box and the workstation reads
them there. A workstation stage that writes a second ledger is the out-of-band
blind spot, and nothing downstream reports it.

⚠️ **D5=NO also moves a line above:** the HUD-observer section says activation is
the 03:00 swap "and not a mid-day restart". A mid-day restart is permitted; what
is not permitted is restarting a game server without explicit permission in the
moment, which is a different rule and still holds.

The original recommendations, kept because the reasoning behind each is still the
argument anyone revisiting one has to answer:

| # | Decision | Recommendation (2026-10-03, superseded where the table above says so) |
|---|---|---|
| D1 | Give `krodssh` a credential that reaches `dodserver` on all 24 instances. | **Yes, as a per-person key (option B).** Note that his existing data-server sudo already reaches the fleet password at rest, so this does not widen what he *can* reach. It makes his access explicit, attributable and revocable on its own. |
| D2 | Shared password (A) or one key per person (B). | **B.** Same reach, but it adds attribution on the game hosts and lets one person be revoked without a fleet-wide rotation. Keep A only as the fallback the wrapper already supports. |
| D3 | The box becomes the only place waves are staged, the operator included. | **Yes.** A second staging location has no lock and keeps its own ledger. Give the operator a personal account (or use `KTP_DEPLOY_ACTOR` as root) so entries name him. |
| D4 | Where the rows live. | **On the box**, as the single home for "what is live", writable by `ktp-deploy`. |
| D5 | HUD-observer activation: nightly swap only, or keep mid-day restarts. | **Nightly only** by default. A mid-day restart is an operator-approved exception, consistent with the standing rule that no game server restarts without explicit permission. |
| D6 | What to do with `cadaver`'s unrestricted sudo on the game hosts. | **Keep it until the shared path has carried one of his deploys end to end**, then narrow it (read-only, or removed). Revoking it first leaves him with no path at all. |
| D7 | Whether `cadaver` and `krodssh` join `ktp-deploy`. | **Yes, both.** Membership is what lets them write the shared ledger and rows. It grants no root they lack. |

## Install

For the operator to run. D1–D7 are ruled (see above); ⛔ the D3 consequence for
the wave ledger is **not** yet resolved in this file, so settle that first. The
⚠️ lines write to the fleet.

```bash
# data server, as root
groupadd --system ktp-deploy
usermod -aG ktp-deploy krodssh; usermod -aG ktp-deploy cadaver   # D7
install -d -o root -g ktp-deploy -m 2775 /opt/ktp-deploy /var/lib/ktp-deploy \
    /var/lib/ktp-deploy/waves /var/lib/ktp-deploy/rollback
git clone --single-branch --branch main --no-tags \
    https://github.com/afraznein/KTPInfrastructure.git /opt/ktp-deploy/KTPInfrastructure
git -C /opt/ktp-deploy/KTPInfrastructure config core.sharedRepository group
chgrp -R ktp-deploy /opt/ktp-deploy/KTPInfrastructure
find /opt/ktp-deploy/KTPInfrastructure -type d -exec chmod g+ws {} +
chmod -R g+w /opt/ktp-deploy/KTPInfrastructure
ln -s /opt/ktp-deploy/KTPInfrastructure/scripts/ktp-deploy.py /usr/local/bin/ktp-deploy

# the ledger history and the rows, copied from the workstation (D3, D4)
#   scp ~/.ktp/waves/*.json  root@<box>:/var/lib/ktp-deploy/waves/
#   scp <project>/.claude/skills/fleet-versions/SKILL.md root@<box>:/var/lib/ktp-deploy/fleet-versions.md
chgrp -R ktp-deploy /var/lib/ktp-deploy; chmod -R g+w /var/lib/ktp-deploy

# option B, per deployer <u>  (option A instead: write the password to
#   /etc/ktp-deploy/fleet-ssh-password, root:ktp-deploy 0640, in a 0750 dir)
sudo -u <u> ssh-keygen -t ed25519 -N '' -C "ktp-deploy-<u>" -f ~<u>/.ssh/ktp_deploy_ed25519
# ⚠️ on each of the five game hosts, append to ~dodserver/.ssh/authorized_keys:
#   from="<data server address>",no-port-forwarding,no-agent-forwarding,no-X11-forwarding <pubkey>
```

## Verify after install

Re-derive. Never assume the install worked because the commands exited 0.

```bash
sudo -u krodssh ktp-deploy stage --preflight-only   # expect: clean, and [ktp-deploy] ... as krodssh
sudo -u cadaver ktp-deploy ledger status --all       # expect: the migrated history, NOT RECORDED actors
tail -2 /var/lib/ktp-deploy/audit.log               # both runs, both actors, the clone's commit
# key option: a game host's auth.log names the ktp-deploy-<u> fingerprint for each run
zgrep 'Accepted publickey for dodserver' /var/log/auth.log | tail -3
# negative control: a second concurrent run is refused and names the first
```

## Follow-ups (not in this change)

- Wrap `ktp-verify-deploy.py` and give it `fleet_ssh_auth()`, so the
  morning-after check runs under the same identity as the stage.
- `--expect-runner`: on the box the tier-2 runner is local. Set
  `KTP_TIER2_SSH_HOST` in the wrapper's environment, or read the runner tree
  directly, once D3 is in place.
- Narrow `cadaver`'s game-host sudo (D6) once the shared path has carried a deploy.
