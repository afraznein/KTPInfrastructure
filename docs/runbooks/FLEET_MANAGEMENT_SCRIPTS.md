# Runbook: refreshing `~/restart-all-servers.sh` and `~/status.sh` on a live host

**What:** replacing the two LinuxGSM management scripts in `/home/dodserver/` on
a host that is already provisioned.

**When:** after any change to the generator block in
`provision/install-linuxgsm.sh`, or when an audit finds a host whose copies do
not match the pinned md5s below.

**This procedure does not restart anything.** It writes two files. Nothing on
the fleet invokes either of them on a schedule — the nightly restart is
`ktp-scheduled-restart.sh`, which is what the `0 3 * * *` crontab line calls.
`restart-all-servers.sh` is a manual admin tool and is reached only by someone
typing it.

That scheduled script has three divergent copies of its own, and syncing them
naively destroys something in either direction — see
[`SCHEDULED_RESTART_LINEAGES.md`](SCHEDULED_RESTART_LINEAGES.md).

---

## Why a runbook exists for two shell scripts

The scripts have no source file. They are heredocs inside
`install-linuxgsm.sh`, and that installer runs exactly once in a host's life, on
a bare machine. So a fix committed here reached no live host, and the copies on
disk drifted apart until three hosts ran one shape and two ran another — for
months, undetected, because nothing compares them.

`--regen-management-scripts` is the missing path. It rewrites both scripts from
the installer and does nothing else: no LinuxGSM download, no SteamCMD, no
instance creation, no crontab edit, no server control.

## Pinned identities

The generator emits byte-identical output on every host — the heredocs are
quoted, so nothing is substituted at install time. That makes an md5 a complete
verification.

| file | md5 |
|---|---|
| `~/restart-all-servers.sh` | `a7d23d9f46ed98b69badf736f85ad8ff` |
| `~/status.sh` | `afa1dac15367b8dcad98598a852d86e0` |

Re-derive rather than trusting the table — it is a pointer, and the generator
may have moved since:

```bash
cd <repo> && HOME=$(mktemp -d) bash provision/install-linuxgsm.sh --regen-management-scripts
```

## Procedure, per host

Run as `dodserver`, never as root — the installer refuses root, because
root-owned scripts in `dodserver`'s home are unusable by the person who needs
them.

```bash
# 1. From the workstation: put the current installer on the host.
#    NY and Chicago carry a stale copy at ~/install-linuxgsm.sh; that copy is
#    the propagation source, so overwrite it rather than working around it.
scp provision/install-linuxgsm.sh dodserver@<host>:~/install-linuxgsm.sh

# 2. On the host, capture what is there now. The fleet keeps no rollback copies
#    of anything, so this is the only copy of the outgoing shape.
ssh dodserver@<host>
md5sum ~/restart-all-servers.sh ~/status.sh
cp -p ~/restart-all-servers.sh ~/restart-all-servers.sh.pre-regen-$(date +%Y%m%d)

# 3. Regenerate. Backs both files up with a timestamped suffix, writes both,
#    and runs `bash -n` on the results before reporting success.
chmod +x ~/install-linuxgsm.sh
~/install-linuxgsm.sh --regen-management-scripts
```

## Verify

```bash
md5sum ~/restart-all-servers.sh ~/status.sh   # must equal the pins above
~/status.sh                                   # read-only: pgrep + ps, nothing else
```

`~/status.sh` is the real check. It shares the discovery block with the restart
script, so a correct instance list from it is evidence about both — and it can
be run on a live host during a match without touching a server. It must list
**five** ports on Atlanta, Dallas, Denver and New York, and **four** on Chicago,
whose 27019 was deleted 2026-07-13.

⚠️ **Do not verify by running `~/restart-all-servers.sh`.** It restarts every
instance and disconnects every player. There is no dry-run flag.

## Rollback

```bash
mv ~/restart-all-servers.sh.bak-<stamp> ~/restart-all-servers.sh
mv ~/status.sh.bak-<stamp> ~/status.sh
```

Regen never deletes a backup and stamps each one to the second, so a second run
cannot destroy the first run's copy.

## What the shipped scripts got wrong

Kept because each is a shape that will look reasonable again in a future script.

**`set -e` plus a baked-in instance list.** The generated restart script looped
over a literal `1 2 3 4 5`. On Chicago the fifth iteration addressed a control
script deleted in July; it exited non-zero and `set -e` ended the run before the
verify block. A four-instance host could not get a report out of the script at
all. An install-time count outlives the install — discover the instances instead.

**`((running++))` starting from zero.** Post-increment evaluates to the *old*
value, so at `running=0` the arithmetic expansion returns exit status 1. Under
`set -e` that killed the verify at the first *healthy* server. `running=$((running + 1))`
does not have this property. The bug hid because it only bites when the counter
is 0, which on a mostly-healthy fleet is the first iteration and nowhere else.

**`[ -f "$f" ] && cp ...`** in the regen path would have the same class of
problem: under `set -e` the AND-list returns 1 when the file is absent and ends
the script before it writes anything. It is written as an `if`.
