### `scripts`: a config KEY on the fleet that is in no source file is now a named finding (2026-10-01)

`ktp-file-distributor.service` never reconciles, so a config set directly on the
instances and never mirrored into `/home/dod/distribute` survives until the next
time anyone touches that file at the source — and is then silently reverted on
all 24. On 2026-08-19 a seven-month-old `discord.ini` was pushed with only its
auth secret changed; it reverted `discord_channel_id` and **deleted
`discord_channel_id_default` outright**. Match-start Discord embeds stopped
posting fleet-wide. It took six weeks and three missed Sundays to notice, because
the failing path is reachable only by competitive `.ktp` play and none ran that
summer. ⚠️ **The alert that should have caught it was a count of failures, and it
read zero — because the code path never ran.**

`audit-distribute-drift.py` already guards the file-level form of that invariant
and remains the first line of defence. `audit-config-key-drift.py` is the
key-level form, and it is additive in the three ways that incident needed:

- **It names the key.** The file-level check reports `discord.ini differs`, and
  the standing report carries ~39 paths in that state — a newly-reverted key
  inside an already-drifted file is invisible in it.
- **It separates a changed value from a deleted key.** md5 calls both `differs`.
  The deleted routing key was the half that broke the embeds and the half nobody
  noticed: KTPMatchHandler reads a missing key as "feature disabled" and posts
  nothing, *successfully*.
- **It reports direction per key.** `source-missing` (the fleet has it, the
  source does not — the next touch deletes it on all 24) and `instance-missing`
  (the source has it, the fleet does not — the next touch imposes it) mean
  opposite things and need opposite fixes.

**Nothing reads as clean without saying how much it looked at.** The headline is
work done — instances compared, paths compared, keys compared — alongside
`inconclusive` (parsed by nothing, so compared for nothing) and
`nothing-to-compare` (both sides empty; they agree and carry no evidence). Exit
`0` ok / `1` findings / `2` the check did not run, and a run that reached 19 of
24 instances with zero findings exits **2**, not 0.

- **Scope comes from the distributor**, by importing `audit-distribute-drift.py`
  rather than reimplementing its matcher — one definition of what would ship. The
  exception mechanism stays `excludePatterns` in `servers.json`. The one list in
  the script can only make it fail, never pass.
- **No value is printed, not even a digest.** These files mix a fleet-wide secret
  with per-instance routing and the weekly audit publishes to a public
  repository; a digest of a 19-digit channel id is a brute-forceable oracle and
  no finding needs one. Identity-shaped key names are redacted by shape.
- **Read-only**, and specifically in the deploy tree: it opens
  `/home/dod/distribute` for reading, `cat`s configs on the instances under
  `ionice`/`nice`, writes no scratch file, and restarts nothing.
- The `key = value` reader moved to `scripts/ktp_config_kv.py` so the Tier-1
  config tests and this check cannot disagree about what a key in `discord.ini`
  is. `parse_dodserver_cfg` deliberately keeps its last-wins collapse; the new
  cvar reader keys a repeated cvar positionally (`exec`, `exec#2`), because a
  collapse loses exactly the line someone deleted.
- Wired into `fleet-audit.yml` as a `continue-on-error` collect step with its own
  state file, and into `fleet-audit-gate.sh` as a transition leg plus two levels:
  short coverage, and a path that could not be parsed.

**First run against all 24 found three armed hazards on `plugins.ini` and the map
configs** — including `ktphudobserver.amxx` loaded on all 24 and listed in no
source file, so the next touch of that file would unload it fleet-wide while
`ktpleague.gg/servers` reads its feed. Detail and the operator decisions it needs:
`docs/runbooks/CONFIG_KEY_DRIFT.md`.
