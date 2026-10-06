# Runbook: drift between `/home/dod/distribute` and the 24 instances

`ktp-file-distributor.service` watches `/home/dod/distribute` on the data server
and pushes any created or changed file to all 24 game instances within ~15s. It
is **purely event-driven**: `FileWatcherWorker` wires a `FileSystemWatcher` and
nothing else. There is no startup sync, no periodic reconcile, and no
after-the-fact comparison anywhere in the service.

That has one consequence, and it is the reason this file exists:

> A config set directly on the instances and never mirrored into the source
> survives until the next time anyone touches that file at the source, and is
> then silently overwritten on all 24.

**The overwrite reports nothing.** The distributor logs a successful
distribution, because it was one.

## The three times this has already happened

| When | File | What was lost | How it was found |
|---|---|---|---|
| 2026-08-19 | `addons/ktpamx/configs/discord.ini` | A January copy was pushed with only its auth secret changed. `discord_channel_id` reverted to a dead value and `discord_channel_id_default` was deleted outright, fleet-wide | Six weeks later. The affected path is reachable only by competitive play, and none ran that summer — match embeds had been failing silently the whole time |
| — | `addons/ktpamx/configs/ktp_maps.ini` | Two generations stale | A manual sweep |
| — | `addons/ktpamx/configs/users.ini` | One generation stale | A manual sweep |

## The invariant

> For every path the distributor **would send** to a given instance, that
> instance's bytes equal the source's bytes.

"Would send" is read out of the distributor's own two config files and never
restated in the checker:

- `appsettings.json` → `WatchPatterns`. A file the service does not watch is
  inert in the tree and is out of scope.
- `servers.json` → per-target `includePatterns` / `excludePatterns`, applied by
  `ServerConfig.Accepts`. Deletions go through the same filter
  (`SftpDistributorService.FilesForServer`), so an excluded path is neither
  uploaded nor deleted on that target.

### Why not something simpler

- **Plain md5 equality, source to instance, for everything.** Wrong for any file
  that legitimately carries per-instance data — `configs/servernamedefault.cfg`
  holds this instance's `hostname` — so it would report 24 permanent findings
  that can never be resolved. The estate has measured what that does: the gate's
  own header records a leg that fired every Monday until someone rewrote it.
- **Uniformity across the 24, ignoring the source.** This is what
  `ktp-verify-deploy.py` asserts, and it is exactly what missed `discord.ini`:
  all 24 agreed with each other and disagreed with the source. Uniformity is
  necessary and nowhere near sufficient.
- **An allow-list of permitted divergence kept in the checker.** It works, and
  it is the wrong place. It would be a second source of truth free to disagree
  with the one that decides what actually ships, it is blind to removals, and —
  the deciding objection — it *documents* the hazard while leaving it armed. The
  file would still be one `touch` away from a fleet-wide overwrite.

### So the exception mechanism is `servers.json`, not the checker

Declaring a path per-instance means adding it to `excludePatterns` on the game
entries in `servers.json`. That one edit does both jobs: it stops the
distributor pushing the file, and it takes the path out of this check's scope
because the check asks the distributor what it would send.

## Reading the report

The check emits `distribute-drift.txt` in the weekly **Fleet Audit** workflow
artifact. Each finding carries a **shape**, and the shape is what decides what to
do about it:

| Shape | Means | What to do |
|---|---|---|
| `uniform` | Every instance agrees with every other, and none agrees with the source | **The fleet is right and the source is stale.** This is the one on a timer. Mirror the instance content back into the source — and read the warning below before writing anything into the tree |
| `per-instance` | Every instance holds a different copy | The file carries per-instance data that nothing has declared. Add it to `excludePatterns` |
| `partial` | Some instances match the source and some do not | A push that reached part of the fleet, or reached it once and not since |
| `absent` | The path is on no instance at all | Usually a file that predates the distributor and has not changed since, so no event has ever fired for it. Kept apart from `partial` because the two read alike in a count and mean opposite things |

`targets reached: N/M` is the completion marker. **An unreachable target is a
failure, not a skip** — a sweep that quietly drops a connection renders
identically to a clean fleet.

## The key-level half

This check compares whole-file md5. It therefore reports `discord.ini differs`
and cannot say *which key*, cannot tell a changed value from a **deleted** key,
and cannot report direction per key. The 2026-08-19 incident needed all three:
the half that broke match embeds was a routing key deleted outright, and a
missing key is not an error anywhere in the stack.

`scripts/audit-config-key-drift.py` is that half, and
**`docs/runbooks/CONFIG_KEY_DRIFT.md`** is its runbook. Same invariant, same
scope source (`WatchPatterns` / `excludePatterns`), same read-only posture, one
level down. Read both when triaging a `uniform` finding on a keyed `.ini`/`.cfg`
-- this one tells you the file is stale, that one tells you what breaks.

## Running it by hand

Read-only. It hashes; it does not push, and it writes nothing into the deploy
tree or onto any instance.

```bash
# on the data server, or anywhere that can read the distributor's config
# and reach the fleet
python3 scripts/audit-distribute-drift.py --verbose
```

Exit `0` clean, `1` drift or an unreachable target, `2` the check could not run.

## Writing into the deploy tree is a deploy

Everything below is why the remediation half of this runbook is short and the
diagnosis half is long.

- **Any file created or changed under `/home/dod/distribute` deploys to all 24
  within ~15s.** Diff against a live instance first, and edit in place
  (`cat new > file`) rather than `rm`/`mv`.
- **Removing a file from the tree DELETES it on all 24**, because deletions sync
  too. The two hazards pull in opposite directions and neither ordering is safe
  on its own: remove the source first and you wipe the file fleet-wide; clean the
  fleet first and the watcher re-pushes what you just deleted. To un-distribute a
  per-instance file: **fix the instances first, then remove the source**, two
  passes, verifying the fleet after each.
  - A path already in every target's `excludePatterns` is exempt from both
    directions, which makes "exclude, then remove" the safe sequence where it
    applies.
- **Keep backups out of the tree.** A backup written inside it replicates.
- **A file mixing a fleet-wide secret with a per-instance value must never be
  distributed whole.**

## Standing findings as of 2026-09-28

Measured against all 24 instances; direction taken from source mtime against
instance mtime, which is the upload time (`SftpClient.UploadFile` does not
preserve timestamps — confirmed against a push made the same morning).

| Paths | Shape | Direction |
|---|---|---|
| 38 map/match configs under `configs/` plus `addons/ktpamx/configs/modules.ini` | `uniform` | **instance-newer.** Fleet-wide edits made 2026-03-17 and 2026-06-11 and never mirrored back. Two of the 39 (`modules.ini`, `addons/extensions.ini`) differ only by a trailing CR |
| `configs/servernamedefault.cfg` | `per-instance` | 24 distinct copies. The source copy happens to equal one instance's, which is what has kept the hazard invisible |
| `motd.txt`, `maps/dod_solitude2.res` and six `sprites/obj_icons/dod_solitude2/*.spr`, `maps/dod_railyard_s9c.*` | `partial` | **source-newer.** February pushes that did not reach every host |
| 14 root-level legacy map configs and `cached.WAD` | `partial` | Absent on one host's five instances; unchanged since 2025-12-29, so no event has ever fired for them |
| `listip.cfg`, three `maps/dod_*.txt` | `absent` | On no instance at all |

### Decisions this needs from the operator

The check reports; it does not fix. These are not the checker's to decide:

1. **The 38 `uniform` configs.** The instances hold the correct content and the
   source is stale. Mirroring them back is a write into the deploy tree, which
   is a fleet-wide deploy of content the fleet already has — low risk, but it is
   still a deploy and it is the operator's act.
2. **`configs/servernamedefault.cfg`.** Add to `excludePatterns` on the 24 game
   entries. Whether the now-inert source copy is then removed is a second
   decision; with the exclusion in place, removing it no longer propagates.
3. **`motd.txt`.** Two hosts run an older copy. Whether a per-region MOTD is
   intended (→ `excludePatterns`) or those hosts simply missed the February push
   (→ let the next touch deliver it) is a product decision, not a drift call.
4. ~~**`addons/ktpamx/configs/plugins.ini`.**~~ **Answered 2026-10-01: 24/24 now
   hold one copy.** The three variants collapsed on measurement — 19 shared one,
   three differed by zero content lines (line endings only, which is why the md5
   moved) and two by a single comment line — so the canonical copy was the
   majority one, pulled from a live host rather than authored. See
   `CONFIG_KEY_DRIFT.md` for the key-level half it closed in the same write.
   ⚠️ **A whole-file md5 census that reports N variants is an upper bound on
   disagreement, not a count of decisions**: diff them before treating a variant
   as a choice someone made.
5. **Non-config artefacts in the tree.** `addons/ktpamx/logs/` and `logs/` hold
   files dated 2025-12-29, and `addons/ktpamx/modules/*.so`, `dlls/*.so` and two
   `.amxx` plugins are stale copies of binaries that ship by wave instead.
   - None of them is in `WatchPatterns`, and they are **absent from all 24** —
     measured, not assumed. So they are inert clutter, not replication.
   - `OnFileChanged` gates deletions through the same pattern test, so removing
     an unwatched file from the tree does not propagate. **Re-check
     `WatchPatterns` immediately before relying on that** — the gate is the live
     config, not this sentence.
6. **`*.amxx` in the tracked `appsettings.json`.** The committed template still
   lists it; the deployed config does not, and the difference is deliberate — on
   2026-09-20 three `.amxx` files went out through the distributor and the
   pattern was removed minutes afterwards. A fresh install from the template
   would re-arm that, and the stale plugins in the tree would ship.
