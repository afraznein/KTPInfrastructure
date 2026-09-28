### The deploy tree is now compared against the fleet it deploys to (2026-09-28)

`ktp-file-distributor.service` pushes any created or changed file under
`/home/dod/distribute` to all 24 game instances within ~15s. It is purely
event-driven — `FileWatcherWorker` wires a `FileSystemWatcher` and nothing else.
There is no startup sync, no periodic reconcile, and nothing anywhere that ever
compares the tree against what the instances hold.

So a config set directly on the instances and never mirrored into the source
survives until the next time anyone touches that file at the source, and is then
silently overwritten on all 24. The overwrite reports nothing, because from the
distributor's side it was a successful distribution.

That has happened three times. On 2026-08-19 a January copy of
`addons/ktpamx/configs/discord.ini` was pushed with only its auth secret
changed; the push reverted `discord_channel_id` to a dead value and deleted
`discord_channel_id_default` outright, fleet-wide, because both had been set on
the instances months earlier. It surfaced six weeks later — the affected path is
reachable only by competitive play, and none ran that summer. `ktp_maps.ini`
went two generations stale the same way and `users.ini` one, both found by a
manual sweep rather than by any check.

- New `scripts/audit-distribute-drift.py`. Read-only: it hashes, and writes
  nothing into the deploy tree, onto any instance, or even into `/tmp` on a game
  host — one `find | xargs md5sum` per target under `ionice`/`nice`.
- **The invariant is scope-derived, not restated.** For every path the
  distributor *would send* to a target, that target's bytes must equal the
  source's. "Would send" is read out of the distributor's own two config files —
  `WatchPatterns` in `appsettings.json`, `includePatterns`/`excludePatterns` in
  `servers.json` — through a port of `PatternMatcher.cs` kept deliberately
  literal. A matcher cleverer than the one that ships would audit a fleet nobody
  deploys to.
- **So the exception mechanism is `servers.json`, not an allow-list here.** A
  file that legitimately carries per-instance data is declared by adding it to
  `excludePatterns`, and that one edit does both jobs: it stops the distributor
  pushing the file and it takes the path out of this check's scope. An
  allow-list in the checker would have been a second source of truth free to
  disagree with the one that decides what really ships, blind to removals, and —
  the deciding objection — it documents the hazard while leaving it armed.
- Plain source-to-instance md5 equality for everything was the other candidate,
  and it is wrong for exactly those files: 24 permanent findings that can never
  be resolved. Uniformity across the 24 — what `ktp-verify-deploy.py` asserts —
  is the wrong axis on its own, and is precisely what missed `discord.ini`: all
  24 agreed with each other and disagreed with the source.
- Findings carry a **shape**, because the shape is what decides the action.
  `uniform` means the fleet is right and the source is stale, which is the one on
  a timer. `per-instance` means a file carrying per-instance data that nothing has
  declared. `partial` is a push that reached part of the fleet. `absent` is one
  that never started — kept apart from `partial` because the two read alike in a
  count and mean opposite things.
- Wired as a step in the existing weekly **Fleet Audit** workflow rather than a
  new cron or a new channel. It runs on the self-hosted runner that already lives
  on the data server, reads the same `/etc/ktp/audit-fleet.json` the rest of the
  audit reads, and its output joins the same artifact, the same triage and the
  same single GitHub issue. A second unwatched alert is worse than none, and this
  estate has measured that.
- `scripts/fleet-audit-gate.sh` gains two legs: the finding set as a
  **transition** (same rule as restart-drift, so long-standing divergence does not
  wake anyone weekly), and the per-instance hazard count as a **level** — the only
  level leg in the file. An undeclared per-instance path is armed rather than
  merely wrong, which is the same argument leg 2 makes for the monitor patch, and
  one line in `servers.json` retires it for good.
- A target that could not be reached is a failure, not a skip, and
  `targets reached:` is the completion marker the gate keys on. A sweep that dies
  renders identically to a clean fleet.
- Hashes are printed 16 characters wide. `audit_redact` blanks any bare 32-hex
  run, so a full md5 in a report published to a public repository would render as
  `<redacted>` and the report would say nothing.
- `docs/runbooks/DISTRIBUTE_DRIFT.md` carries the mechanism, how to read a shape,
  and the standing findings.

**Measured on 2026-09-28, all 24 instances, 24/24 reached:** 3886 watched paths,
71 with drift — 38 `uniform`, 28 `partial`, 4 `absent`, and 1 `per-instance`.
The `uniform` set is fleet-wide config edits from 2026-03-17 and 2026-06-11 that
were never mirrored back; two of them differ only by a trailing CR. The single
`per-instance` path is `configs/servernamedefault.cfg`, which holds each
instance's `hostname` and is in no `excludePatterns` — one touch of the source
gives 23 servers the 24th's name. Its source copy happens to equal one instance's,
which is what has kept it invisible.

Remediation is deliberately not here. Writing into that tree is a fleet-wide
deploy and removing from it deletes fleet-wide; the runbook states the sequencing
and names the five decisions this audit surfaces as the operator's.
