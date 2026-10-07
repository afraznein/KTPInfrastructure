# Runbook: config KEYS on the fleet that are not in the distributed source

`ktp-file-distributor.service` watches `/home/dod/distribute` and pushes any
created or changed file to all 24 game instances within ~15s. It is purely
event-driven: no startup sync, no periodic reconcile, no comparison anywhere.
`docs/runbooks/DISTRIBUTE_DRIFT.md` covers the file-level consequence. This file
covers the key-level one, which is the same invariant and a different finding.

> A config **key** set directly on the instances and never mirrored into the
> source survives until the next time anyone touches that file at the source,
> and is then silently deleted or reverted on all 24.

## The incident this exists for

On **2026-08-19** a seven-month-old copy of
`addons/ktpamx/configs/discord.ini` was pushed to the deploy path with **only
its auth secret changed**. The push:

- reverted `discord_channel_id` to a channel that no longer existed, and
- **deleted `discord_channel_id_default` outright.**

Both had been set directly on the instances months earlier and never mirrored
back. Match-start Discord embeds stopped posting on all 24. Of the seven
channels configured, exactly one was refused and the other six answered fine,
so the relay, its auth and the bot token were never implicated.

**It took six weeks and three missed Sundays to notice.** The failing path is
reachable only by competitive `.ktp` play, and none ran between June and
September. ⚠️ **The alert that should have caught it was a count of failures,
and it read zero — because the code path never ran.** An absence of failures is
not evidence of health, and that is the single idea this check is built around.

## Why the file-level check was not enough

`audit-distribute-drift.py` guards the same invariant by whole-file md5 and is
the first line of defence. It is not sufficient for three reasons, each of which
the 2026-08-19 incident needed:

1. **It cannot name the key.** It reports `discord.ini differs`. The standing
   report currently carries ~39 paths in that state — long-standing, triaged,
   and exactly the kind of list a human skims. A newly-reverted key inside an
   already-drifted file is invisible in it.
2. **It cannot separate a changed value from a deleted key.** Both are
   `differs`. The deleted routing key was the half that actually broke the
   embeds, and the half nobody noticed: **a missing key is not an error anywhere
   in the stack.** KTPMatchHandler reads a missing key as "feature disabled" and
   posts nothing, successfully.
3. **It cannot report direction per key.** A key the fleet has and the source
   does not is one problem; a key the source has and the fleet does not is the
   opposite problem. They need opposite fixes.

Note what neither check is: **uniformity across the 24**, which is what
`ktp-verify-deploy.py` asserts, is the wrong axis on its own. In the discord.ini
case all 24 agreed with each other and disagreed with the source — which is
precisely the state that was about to be destroyed.

## Reading the report

`config-key-drift.txt` in the weekly **Fleet Audit** artifact. One row per
`(path, key)`, each carrying a **kind** and a **shape**.

| Kind | Means | What the next touch of the file does |
|---|---|---|
| `source-missing` | The fleet holds this key; the source does not | **Deletes it on all 24.** The 2026-08-19 shape |
| `differs` | Both sides set it, to different values | **Reverts the fleet to the source value** |
| `instance-missing` | The source holds this key; the fleet does not | **Imposes it on all 24** |
| `file-missing-instance` | The whole file is absent on at least one instance | A push that never landed there |

| Shape | Means | What to do |
|---|---|---|
| `uniform` | Every compared instance agrees with every other, and none with the source | **The fleet is right and the source is stale.** The one on a timer. Mirror it back — and read the deploy-path warning below first |
| `per-instance` | Every instance holds a different value | The key legitimately varies. The file needs an `excludePatterns` entry, or it is one touch from being flattened to a single copy |
| `partial` | Some instances, not all | A push that reached part of the fleet, or a sweep that reached part of it |

### The headline is the part that matters

```
instances compared: 24/24  paths compared: 97/100  keys compared: 34612
  findings: 60  inconclusive: 3  nothing-to-compare: 4
```

Every number there is **work done**, deliberately, because `findings: 0` was the
August alert and it was zero for the wrong reason. Read it in this order:

- **`instances compared: N/24`.** Anything but `24/24` is **not a clean fleet**,
  whatever the finding count says. A partial sweep reported as clean is this
  incident all over again.
- **`inconclusive`.** Paths that could not be parsed, so **nothing was compared
  for them**. That is not agreement. Each needs either a reader or an
  `excludePatterns` entry; the list is finite and the gate nags until it is zero.
- **`nothing-to-compare`.** Both sides hold zero keys. They agree, and they
  carry no evidence — kept separate so `paths compared` can never be read as
  "paths that actually had something to say".

### Exit codes

| Code | Means |
|---|---|
| `0` | Every expected instance compared, every path parsed, every key agrees |
| `1` | Findings: a key differs, or is missing on either side |
| `2` | **The check did not run.** Short coverage, an unreachable target, a required path unparsable, no credential source — or no findings but unparsed paths, which answers nothing |

⚠️ **A `2` is never clean.** It means the question was not answered.

### No value is printed, and that is not negotiable

`discord.ini` mixes a fleet-wide secret with per-instance routing, `users.ini`
carries admin passwords, `ktp.ini` carries the live season match password — and
this report is published to a **public** repository as a workflow artifact. So
the report carries key **names**, kinds, shapes and counts, and nothing else.

Values are compared in memory by digest and **the digests are not printed
either**: a digest of a 19-digit channel id or a short password is a
brute-forceable oracle, and no finding here needs one. Read the value on the
box. Key names are themselves redacted where a name can *be* identity (a
SteamID, a 17-digit id, a quoted admin name), and the whole report then goes
through `audit_redact.redact_diagnostic` as a backstop.

## Running it by hand

Read-only. It opens the distribute tree for reading, `cat`s configs on the
instances under `ionice`/`nice`, writes no scratch file anywhere, and restarts
nothing.

```bash
# On the data server, where the distributor config and /etc/ktp/audit-fleet.json
# both already exist:
python3 scripts/audit-config-key-drift.py --verbose

# One path, when triaging a single finding:
python3 scripts/audit-config-key-drift.py --path addons/ktpamx/configs/discord.ini

# Off the box: reads the distribute tree over SFTP, credentials from a local
# ktp_hosts.py. Neither source is committed and neither is printed, and no
# address is baked into the script.
KTP_HOSTS_MODULE=/path/to/ktp_hosts.py KTP_SOURCE_HOST=<data server> \
  python3 scripts/audit-config-key-drift.py --path addons/ktpamx/configs/discord.ini
```

### Proving it still catches the original incident

```bash
python3 scripts/audit-config-key-drift.py --selftest    # no fleet, no credentials
```

Replays 2026-08-19 offline and asserts that `discord_channel_id` reads as
`differs`, that `discord_channel_id_default` reads as `source-missing`, that
both are `uniform` across 24, and that the auth-secret rotation — the one change
that was *meant* to happen — is **not** a finding. `tests/unit/test_config_key_drift.py`
runs the same thing on every PR. ⚠️ **Never assert its exit code through a
`| head`/`| tail`** — the pipe launders it to 0.

### Hand-checking a finding: four ways the assertion lies, not the file

All four were hit in one sitting while verifying the `plugins.ini` write, and
each one printed alarm on a file that was already correct.

- **Strip comments before you count anything.** `;` and `#` lines hold keys that
  are not set. A "`debug` must be 0" check matched three commented stock lines
  and read as a failure. (The checker's own first sweep had the same bug.)
- **Anchor with `^`.** A pattern needing a character before the token (`[^;[:space:]].*NAME`) returns
  0 on a line that *starts* with it, which is the normal shape for a plugin entry.
- **`grep -c` counts a match SET, not the lines you mean.** Comparing 3 against
  11 compared every occurrence in two files rather than the three lines under test.
- **Test path CONTAINMENT, never a substring.** `echo "$B" | grep -q distribute`
  matches `/root/distribute-backups` and reports a backup as unsafely *inside*
  the deploy tree. Use `case "$(readlink -f "$B")/" in /home/dod/distribute/*)`.

➡️ Carry a positive control and a nonsense control on every one of these: an
assertion that cannot fail is the same evidence as one that cannot pass.

## Scope comes from the distributor, never from a list in the checker

Which paths and which targets are read out of the distributor's own two config
files — `WatchPatterns` in `appsettings.json`, `includePatterns` /
`excludePatterns` per target in `servers.json` — by importing
`audit-distribute-drift.py` rather than reimplementing the match. A second
matcher would be a second source of truth free to disagree with the one that
decides what actually ships.

So **the exception mechanism is `servers.json`, not the checker.** Declaring a
path per-instance means adding it to `excludePatterns` on the game entries,
which both stops the distributor pushing it and takes it out of this check's
scope.

The one list in the script, `REQUIRED_PARSABLE`, **cannot make anything pass**:
a path named there which is absent, unparsable, or short of full coverage forces
exit 2. It only ever makes the check louder.

## Writing into the deploy tree is a deploy

The remediation half of this runbook is short for the same reason it is in
`DISTRIBUTE_DRIFT.md`, and that file is the authority on it:

- **Any file created or changed under `/home/dod/distribute` deploys to all 24
  within ~15s.** Diff against a live instance first, and edit in place
  (`cat new > file`) rather than `rm`/`mv`.
- **Removing a file from the tree DELETES it on all 24.** Fix the instances
  first, then remove the source — two passes, verifying after each.
- **Keep backups out of the tree.** A backup written inside it replicates, and
  the FastDL exclude matches exact extensions, so a `*.cfg.bak-*` still reaches
  FastDL.
- **A file mixing a fleet-wide secret with a per-instance value must never be
  distributed whole.** `discord.ini` is that file, and it is why this runbook
  exists.

## Standing findings as of 2026-10-01

First run against all 24. Both parser artifacts in the very first sweep (`;` and
`#` comment lines read as keys) were fixed before these numbers; they had been
hiding two of the three items below.

| Path | Key(s) | Kind | Shape | What the next touch does |
|---|---|---|---|---|
| `addons/ktpamx/configs/plugins.ini` | `ktphudobserver.amxx` | `source-missing` | `uniform` 24/24 | **Unloads KTPHudObserver fleet-wide.** It is enabled on all 24 by operator ruling (2026-08-25) and `ktpleague.gg/servers` reads its feed |
| `addons/ktpamx/configs/plugins.ini` | 8 KTP plugins | `differs` | `uniform` 24/24 | **Arms a `debug` flag the fleet does not carry.** `config-tests.yml` names `debug` promoted to online as a JIT-killer |
| 34 × `configs/ktp_*.cfg` | `mp_clan_readyrestart` | `instance-missing` | `uniform` 24/24 | Re-adds a ready-restart cvar to live match configs |
| `configs/ktpovertime.cfg` | `sv_send_logos` | `source-missing` | `uniform` 24/24 | Deletes it on all 24 |
| `configs/ktp_railyard.cfg`, `_railyard_b6.cfg` | `exec` | `differs` | `uniform` 24/24 | Changes what the map config execs |
| 13 root-level legacy map configs | whole file | `file-missing-instance` | 5 instances | Nothing — unchanged since 2025-12-29, so no event has ever fired. Matches the file-level check's standing finding |
| `listip.cfg` | whole file | `file-missing-instance` | 24 | On no instance at all. Also a standing file-level finding |
| `grenade_loadout.ini`, `ktp_maps.ini` | — | `inconclusive` | — | Mixed shapes: `key = value` and bare-token lines in one file. Needs a declared reader or an `excludePatterns` entry |

### Decisions this needs from the operator

The check reports; it does not fix. None of these is the checker's to decide.

1. ~~**`plugins.ini`.**~~ **Answered and written 2026-10-01** — both halves in one
   write, 24/24 now on a single copy with `KTPHudObserver` loaded and no
   uncommented `debug`. "Which copy is canonical" turned out to have a
   measurement for an answer rather than a ruling: 19 of 24 already ran the same
   copy, and the five others differed by one comment line or by whitespace, so
   the reconciled file needed pulling from a live host, not authoring. Writing it
   converged those five as a side effect, which is what made it a change to 24
   instances and not only to the source. Three `debug` mentions remain in the
   file and are **correct** — commented-out stock AMXX lines above the KTP
   section.
2. ~~**`mp_clan_readyrestart` in 34 source map configs.**~~ **Ruled 2026-10-05
   (operator): the fleet is right — mirror the removal back.** Done the same day
   as part of a 36-file mirror-back; the source's 34 `configs/ktp_*.cfg` now carry
   the disabled form, the fleet was unchanged by the push, and a sweep since finds
   the cvar set by no file in the tree.

   🔑 **What this closed was a latent fleet-wide match-rules change, not an
   inconsistency.** While the source set it and the fleet did not, *any* touch of
   those 34 files for any unrelated reason would have delivered
   `mp_clan_readyrestart 1` to all 24 — exactly what this table's "what the next
   touch does" column said.

   📌 **The pre-change value is `1`, and it stayed recoverable from the disabled
   line itself**, which keeps the value after the marker rather than deleting it.
   Prefer that shape over removing a line: it survives into every later copy and
   needs no backup to read.

   ⚠️ **But the marker is `#`, and `#` is NOT a comment to this engine — only `//`
   is** (`COM_Parse`, `rehlds/engine/common.cpp`, which skips `//` and nothing
   else). The line is tokenized as a command named `#`, found to be neither
   command, alias nor cvar, and then dropped **in silence**, because
   `Cmd_ExecuteString_internal` only prints for an unknown command when
   `sv_echo_unknown_cmd` is `1` — and that cvar is set in no `dodserver.cfg` on the
   fleet. So the disable works and costs nothing, and it works for a different
   reason than the one a reader assumes. ➡️ **Use `//` for a new one**, so the
   disable does not depend on a silent-unknown-command path.
3. **The two unparsable configs.** Give them a reader in
   `scripts/ktp_config_kv.py`, or declare them out of scope in `servers.json`.
   Until then the check reports that it has not compared them, which is honest
   and will keep nagging.
