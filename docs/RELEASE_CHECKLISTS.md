# Release checklists — C++ layer and KTPAntiCheat

Moved out of the stack-root `CLAUDE.md` on 2026-07-27. The **plugin** bump checklist stayed there (short, used constantly); these two are longer and consulted per-release.

### Module / Engine Release Checklist (KTPReHLDS, KTPAMXX, KTPReAPI, KTPAmxxCurl)

**Why this exists:** plugins have the checklist above, which forces a README/CHANGELOG touch on every bump. The C++ layer had no equivalent — it deploys by md5 verification, and docs got updated only when someone remembered. The 2026-07-19 documentation audit found *every* C++ repo had drifted worse than *every* Pawn plugin, including an `extensions.ini` path that was wrong in five files and would silently degrade a server to vanilla HLDS. Step 3 is the leg that was missing.

**1. Commit before you build.** Build scripts bake the git SHA (and a `-dirty` marker) into the binary, and KTPAMXX additionally bakes a per-minute build timestamp. Commit the change first, then build the artifact you intend to ship. **Never rebuild after md5-verifying** — the md5 moves and the verification is void. Local rebuilds are not reproducible; the fleet md5 is the truth, not a local one.

**2. Version identity is the md5, never the banner.**
- **ReHLDS:** the version is what you write in the CHANGELOG title. Do *not* hand-edit `rehlds/version/version.h` `VERSION_BUILD` — `appversion.h` is generated at build time from `git rev-list --count` (`rehlds/version/appversion.sh:48`), so the console banner drifts from the CHANGELOG by design (`version.h` reads 904 while the shipped cut is `.929`).
- **KTPAMXX:** console stamps `<ver>.<buildno>`; any rebuild churns it.
- **ReAPI / AmxxCurl:** `reapi/version/version.h` and the CMake project version.

**A drift-baseline PR (e.g. a re-pin of `provision/expected-binaries.conf` for `scripts/audit-fleet-drift.py`) goes stale the same way, on a shorter clock.** Its md5 pins are only ever as current as the fleet was when the PR was opened. If a nightly `.new` wave lands before the PR merges, the pins are already wrong at merge time — merging it either reports drift that isn't real, or silently stops flagging drift that is. **Re-derive the baseline against the live fleet at merge time, never at PR-open time**, and never treat a repo-vs-`CLAUDE.md` comparison as an independent check of the fleet — both are documents, and a wave can move ahead of either one without moving the other.

**3. Docs — do not skip.**
- CHANGELOG entry for the cut. If a change was reverted before shipping, say so in the same entry; a changelog that documents a reverted flag is worse than silence.
- **Re-verify the README build command from a clean clone's perspective, not your tree.** Gitignored maintainer wrappers (`build_linux.sh`) are invisible to a clone and are the single most common rot here.
- **Re-verify install paths against a live host**, not memory. Both the file location *and* its contents.
- If a build system, path, or config location changed, **grep the whole stack for the old string** — these errors propagate across repos and outlive the change by months.

**4. Stage and deploy.** Use **`KTPInfrastructure/scripts/stage-wave.py`** — the standard fleet-staging tool. It drops `<file>.new` on all 24 instances *and* enforces the discipline this step depends on: the pre-stage attribution gate (won't stack onto an existing `.new`), `--expect NAME=MD5` md5-pin (won't ship an accidental rebuild), perms mode-match, md5 24/24 verify, and it prints the morning-after `ktp-verify-deploy.py` command. It never restarts a server. If staging by hand instead, drop the artifact as `<file>.new` in its real directory. The nightly auto-swap glob is **explicit, not recursive** — `serverfiles/*.new`, `ktpamx/dlls/*.new`, `ktpamx/modules/*.new`, `ktpamx/plugins/*.new`. Any new deploy path requires an explicit edit to `scripts/ktp-scheduled-restart.sh`. KTPAMXX ships alone on its own nightly, never stacked with an engine cut.

**5. Post-activation verify** (fleet is **24** instances):
- md5 matches on 24/24, no leftover `.new`.
- **Flip the root `CLAUDE.md` version-table row STAGED→LIVE** with the md5 you just verified — the fleet md5 is the source of truth, not the row's prior claim. Skipping this is how the ReAPI (364→365) + AmxxCurl (1.3.14→1.3.15) rows drifted a full version behind while the fleet was correct (caught + reconciled 2026-07-22), and how KTPCvarChecker (7.36 vs a fleet on 7.37) and KTPMatchHandler (0.10.168 vs 0.10.170) were *both* stale out of the single 2026-09-01 wave, unnoticed for a day.
  🔑 **This step is now GATED, not remembered.** `stage-wave.py` records `(basename, md5, version)` at stage time and refuses to stage the NEXT wave while an earlier one has activated and its row still names the build it replaced. Two rows skipped in one wave is a process defect, not two mistakes — the control that failed was "someone comes back in the morning", so the check sits on the action that was going to happen anyway. Editing the row is what clears it; there is no second command to remember.

  ```bash
  python3 scripts/ktp-wave-ledger.py reconcile   # re-reads the fleet, then gates on CLAUDE.md
  python3 scripts/ktp-wave-ledger.py status      # what is pending, and what has activated
  ```

  Exit **1** means the row is stale (the fleet moved, the record did not). Exit **2** means it could not check — an unreadable `CLAUDE.md` or an unreachable fleet is never reported as a pass. `--no-fleet` checks the row against the recorded md5 alone and says so in its output; `--allow-unreconciled` on `stage-wave.py` overrides the gate, for a deliberate stack only.
  ⚠️ **If the wave did NOT activate cleanly, do not flip the row to clear the gate** — find the leftover `.new` first (`ktp-verify-post-swap.sh`). A gate satisfied by a wrong edit is worse than one that blocked.
  📌 The ledger lives at `$KTP_WAVE_LEDGER_DIR` (default `~/.ktp/waves`), outside this public repo; `$KTP_CLAUDE_MD` points at the root `CLAUDE.md` if it is not one level above the checkout.
- Cores: `find /tmp -maxdepth 1 -name 'core.*' -mtime -1` — **not** the game trees. `core_pattern` is `/tmp/core.%e.%p.%t`, so a game-tree search matches only `core.so`/`core.ini`/`core.wav` and looks clean whether or not anything crashed.
- `ktp_extension_loaded` — proves extension mode actually initialized. A missing or misplaced `dod/addons/extensions.ini` returns silently (`sys_dll.cpp:1077`) and degrades the server to vanilla HLDS: no wall-penetration fix, no cvar enforcement, no match handler.
- **Re-sync the Tier-2 runner stack** — see the section below. This is the step that keeps a Tier-2 green meaning anything.

### Tier-2 runner re-sync

The Tier-2 runner is a **must-match-fleet** environment: a green suite is evidence *only* because it ran against the stack production runs. This step used to read `Re-sync the Tier-2 runner stack (above)` and point at no section, in a document whose only other mention of Tier 2 was that line. The detector was built and works — `scripts/ktp-tier2-stack-drift.py`, inside the 6h `ktp-tier2-heartbeat` cron, which alerted `ok -> drift` within hours of the 2026-08-26 ABI wave. Nothing existed to act on the alert, so the runner stayed on the pre-wave engine, core, dodx and reapi. A green run in that state does not merely fail to inform, it misinforms.

**When.** After post-activation verify passes — never before. The runner mirrors the LIVE fleet, so syncing from an instance whose state is not yet verified relocates an unverified stack rather than establishing anything. The deliberate exception is a *pre-activation gate*, where the runner is meant to LEAD the fleet; that is `stage-runner.py`'s job, not this one.

**What the operator runs**, from the workstation:

```bash
export KTP_TIER2_SSH_HOST=<data server>        # the runner is co-located there
export KTP_TIER2_SSH_KEY=~/.ssh/id_ed25519     # that box is keys-only
export KTP_DRIFT_REF_HOST=<atlanta baremetal>  # the same reference the tripwire uses
export GAME_SSH_PASSWORD=<fleet dodserver>

python3 scripts/sync-runner-stack.py           # report only — nothing is written
python3 scripts/sync-runner-stack.py --apply   # do it
```

Without `--apply` the tool only reports. With it, it backs up each drifted file on the runner before overwriting, and re-reads the md5 after the pull *and* after the push. It refuses while a Tier-2 run is live, and refuses while the reference instance is holding staged `.new` files, because a sync into a pending wave is stale again at the next 03:00 — `--ignore-running` and `--ack-pending-wave` override each, and say so in the output.

**What it deliberately does not cover.** Each of these needs its own look on every wave:

- **Test-mode plugins.** KTPMatchHandler and KTPPracticeMode are `KTP_TEST_MODE` builds; byte-equality with the fleet would be *wrong*, so md5 says nothing about them. Check with `stage-runner.py --show`.
- **KTPHudObserver.** `tier2-integration.yml` rebuilds it from upstream every run, so a copy from the fleet is overwritten within one run.
- **Configs.** Excluded by the tripwire and by this tool alike. `ktp_maps.ini` once went stale unnoticed while everything binary was in sync — sweep `configs/` by hand.

**Confirm it landed** by making the tripwire agree, not by re-reading the tool's own output:

```bash
ssh <data server> /usr/local/bin/ktp-tier2-heartbeat.sh
```

### KTPAntiCheat Release Checklist (Desktop + API)

Full step-by-step in `KTPAntiCheat/docs/RELEASE.md`. Critical rule: **the version is single-sourced in `KTPAntiCheat/Directory.Build.props`** (D1, since 0.7.2) — bump it there and never add a per-project `<Version>` back to a csproj (that overrides the props value). Core/Desktop/Api inherit it, and the client display version reads from `KTPAntiCheat.Core`'s assembly, so a bump that misses Core ships a binary reporting the OLD version (caught 2026-05-07: 0.4.4 launched showing "0.4.2") — the single source is what prevents that. Run `vac-safety-review` agent BEFORE building any change touching `KTPAntiCheat.Desktop/**` or `KTPAntiCheat.Core/**`.

**Standing per-release deliverables (EVERY version, not just scope-changing ones):** in addition to the `Directory.Build.props` version bump + CHANGELOG/README + SAFE_APIS rows, each release MUST also ship: (1) **guide version stamp** — bump the version in the tester landing (`docs/web/index.html` + `README.html`) and the admin guide (`docs/admin/ADMIN_GUIDE.html` `Rev:` line + dated entry) so the guides never lag the client; (2) **pastable Discord announcement** — compose from `KTPAntiCheat/docs/RELEASE_ANNOUNCEMENT_TEMPLATE.md`, save to the **stack-root** `N:\Nein_\KTP Git Projects\discord-embeds\anticheat-<ver>-announcement.md` (where 0.7.1–0.7.3 live and where RELEASE.md step 13's `../../discord-embeds/` resolves — NOT the repo-local `KTPAntiCheat/discord-embeds/`, where 0.7.4's landed by mistake); (3) **signed exe on the operator Desktop** — copy the signed single-file exe to `KTPAntiCheat-<ver>.exe` on the Desktop resolved via `[Environment]::GetFolderPath('Desktop')` (OneDrive-redirected on this box; NOT `%USERPROFILE%\Desktop`). RELEASE.md steps 6/8/13/14 (step 12 is the PUBLIC-COPY GATE, added 2026-07-27: run it BEFORE writing any tester-page or announcement text — publish outcomes, never posture, and a server-side-only release gets ONE line rather than internals).

---
