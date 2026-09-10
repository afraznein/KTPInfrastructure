# Runbook: how audits reach the fleet, and why they stall

**Measured 2026-09-10**, read-only, from a workstation and from the data server
(`neindataatl`) as `krodssh`.

This document exists because "run the audit" turns out to mean four different
things depending on who is asking, and only one of them works today. It also
records the finding that came out of checking: **the weekly audit has been
running against a repo checkout 135 commits old, and it says so every week into
a log nobody reads.**

## The access model today

| Path | Reaches the 5 game hosts | How |
|---|---|---|
| Weekly cron on the data server | **yes** | `root` → `/usr/local/bin/ktp-fleet-audit.sh` → `/opt/ktp-infra/scripts/audit-fleet-drift.py` → paramiko SSH as `dodserver`, password from `/etc/ktp/audit-fleet.json` (root, 0600) |
| An operator at a workstation | **yes** | `KTP_FLEET_SSH_PASSWORD` or `~/.ktp_fleet_ssh_password`, used by `deploy-to-fleet.py`, `deploy-restart-script.py`, `ktp-restart-drift.py` |
| `krodssh@api.ktpdod.com` | **no** | Holds no private key. `sudo` needs a password. Not in `adm` / `systemd-journal`, so the journal is unreadable |
| An agent or CI job on this workstation | **no** | `dodserver@<ip>` refuses the workstation key on all five hosts, checked individually |

Everything the fleet audit does runs as **root on the data server, SSHing to
five hosts with a shared `dodserver` password**. `audit-fleet.json.example`
already carries the note: *"Migrate to `key_filename` when feasible — the shared
`dodserver` password is weak."* That is the whole trust model, and it is why a
workstation cannot simply be handed the same access.

### What `krodssh` can read without any of that

More than expected, and it is the useful half:

- `/var/log/ktp-audit-*.md` — every weekly report, world-readable (`0644`)
- `/var/log/ktp-fleet-audit.log` — the wrapper's own run log
- `systemctl show` / `list-units` / `list-timers` for the whole data server
- the `/opt/ktp-infra` tree

So the *results* of a fleet audit are already reachable read-only. What is not
reachable is running a **new** check that the weekly audit does not yet perform.
That distinction is the whole design constraint for anything automated — see
[Toward automated audits](#toward-automated-audits).

---

## The finding: the audit's own baselines are 135 commits stale

`/opt/ktp-infra` is at `8ef66d3` ("scripts: provider-diverse offsite archive
pusher (#204)"), **135 commits behind `origin/main`**. Its last fetch was
2026-09-07 22:51.

The wrapper is not blind to this. `ktp-fleet-audit.sh` reports staleness on
every run and deliberately never pulls — a weekly root cron that self-updates
would execute whatever last landed on main, with SSH to all five game hosts.
That reasoning is sound and should not change. But the report goes here:

```
Baselines: a20d6e7, 74 behind origin/main, 0 local modification(s)
NOTE: baselines are behind origin/main -- drift may be stale, not real.
Baselines: 8ef66d3, 133 behind origin/main, 0 local modification(s)
NOTE: baselines are behind origin/main -- drift may be stale, not real.
```

Two runs, 2026-08-31 and 2026-09-07, drifting 74 → 133 → 135. Both lines are in
`/var/log/ktp-fleet-audit.log`, which the cron appends to and nothing reads. The
check fires correctly, and its output is discarded by the same mechanism the
five incidents in [`ALERT_COVERAGE.md`](ALERT_COVERAGE.md) were discarded by: it
is detected, it is recorded, and nobody is told.

### What this does and does not invalidate

**Does not:** every `expected-*.conf` is byte-identical between `8ef66d3` and
`main`, and so is `fleet-drift-snapshot.sh`. The 2026-09-07 report is comparing
the fleet against the same baselines `main` declares. Its findings are real.

In particular the **15 binary md5 drift items are genuine and not an artifact of
the stale checkout** — all five hosts agree with each other and disagree with
`provision/expected-binaries.conf`, which the stale commit and `main` define
identically. The 09-07 run recorded `+10 new`, so ten of those appeared that
week: something was deployed to the fleet without the pins being updated. That
is a real open item and it is not in this document's lane.

**Does:** any check added to the repo after `8ef66d3` is not running. The
monitor patch check from #297 is in `main` and is **not** on the data server, so
next Monday's audit will not include it. Confirmed:
`/opt/ktp-infra/scripts/ktp-monitor-patch-check.sh` does not exist.

This is the same class of trap as
[`FLEET_MANAGEMENT_SCRIPTS.md`](FLEET_MANAGEMENT_SCRIPTS.md): **merged is not
deployed, and a green report is not evidence that your new check ran.** A check
that was never copied to the box produces exactly the same output as a check
that passed.

There is a second copy of the same shape: `/usr/local/bin/ktp-fleet-audit.sh` is
a deployed file dated 2026-08-25, not a symlink into `/opt/ktp-infra`. Editing
the wrapper in the repo changes nothing on the box either.

### Owed step

Someone with root on the data server pulls `/opt/ktp-infra` to a reviewed commit
before the monitor check can run weekly. That is a deliberate act, per the
wrapper's own reasoning — not something to automate into the cron.

Verify afterwards by re-deriving, never by checking that a PR merged:

```bash
git -C /opt/ktp-infra log --oneline -1
git -C /opt/ktp-infra rev-list --count HEAD..origin/main     # want 0
ls -l /opt/ktp-infra/scripts/ktp-monitor-patch-check.sh      # must exist
grep -c "LINUXGSM MONITOR" /var/log/ktp-audit-*.md | tail -1 # after the next Monday run
```

---

## Toward automated audits

The instinct is to give an agent fleet credentials. That is the expensive
answer: it widens the blast radius of the weakest credential in the estate (a
shared `dodserver` password) to reach a class of caller that cannot be asked to
think twice before a sweep, during a live season.

The cheap answer follows from the access table above. **The read path already
works.** An agent on this workstation can already read every weekly report over
`krodssh` — it read the 2026-09-07 one while this document was being written.
What it cannot do is cause a *new* question to be asked of the fleet.

So the split worth building toward:

1. **Publish, do not grant.** Anything an audit already computes should be
   readable without fleet credentials. Reports are; the wrapper log effectively
   is not, because nothing surfaces it. The staleness NOTE above is the proof
   that "written to a log" and "reported" are different things.
2. **Make new checks cheap to add, not new access cheap to obtain.** The pattern
   #297 used — emit `=== SECTION ===` facts, let `audit-fleet-drift.py` upload
   and run the script, compare across hosts — costs one file and needs no new
   credential. That is the extension point. Every new question should arrive as
   a snapshot section, and the only privileged step stays the weekly root cron
   that already exists.
3. **Close the deploy gap first, or automation compounds it.** An agent that can
   author checks against a checkout 135 commits behind will confidently report
   on checks that never ran. Whatever pulls `/opt/ktp-infra` — a human on a
   reviewed commit, a gated job, a release tag — has to exist before more
   automation lands on top of it, or every added check inherits the same silence.
4. **On-demand runs need a narrower door than the audit's.** If an agent should
   be able to trigger a sweep between Mondays, the thing to expose is a
   *triggerable, read-only, fixed-payload* run on the data server — not SSH
   credentials for five game hosts. The audit is already read-only by
   construction; what it lacks is a caller that is not `cron`.

None of that is scoped here. This document is the access map it would have to
start from, and the record that the current path has been quietly stalling since
at least 2026-08-31.

## Open questions for the operator

1. Who pulls `/opt/ktp-infra`, and on what trigger? It has no owner today.
2. Should `/usr/local/bin/ktp-fleet-audit.sh` keep being a separate deployed
   copy, or become a symlink into the checkout? Two unversioned surfaces is one
   more than necessary.
3. The `+10 new` binary drift items in the 2026-09-07 report: was there a fleet
   deploy in the week to 09-07 whose pins were not updated?
4. Is a `dodserver` key for automation acceptable in principle, or should
   automated auditing stay strictly behind the data server's existing root cron?
   Point 4 above assumes the latter.
