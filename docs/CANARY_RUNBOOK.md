# Production Canary Runbook

**Status:** Operational. Pattern in active use.
**Sibling runbook:** [`KERNEL_EXPERIMENT_RUNBOOK.md`](KERNEL_EXPERIMENT_RUNBOOK.md) for kernel-cmdline experiments.
**Last updated:** 2026-04-30

This runbook is the canonical pre-flight + toggle pattern for **single-instance production canaries** — toggling a cvar, cfg setting, or feature flag on one host (typically ATL:27019, the long-standing research slot) ahead of fleet-wide rollout.

The canary's whole purpose is to introduce **one new variable** against an otherwise-baseline fleet. Pre-flight exists to confirm the baseline is actually baseline before flipping the variable. Get the pre-flight wrong and you either (a) miss a real bug masking the change or (b) abort spuriously on a healthy fleet — both happened in 2026-04 and motivate this runbook.

---

## 1. When to use this pattern

- Single-instance cvar toggle (e.g. `sv_send_logos 0 → 1` HPAK canary)
- Single-instance cfg edit (e.g. `startparameters` change for a `-pingboost`/`-absgrid` experiment)
- Single-instance binary swap that bypasses the normal `.new` flow

**NOT for:** fleet-wide changes (use the normal deploy path), kernel cmdline changes (those are host-level — see `KERNEL_EXPERIMENT_RUNBOOK.md`), or anything that requires a restart (canaries should be runtime-applicable; restart-required changes belong in the next nightly swap).

---

## 2. Pre-flight rules — live-binary md5/size assertions (current pattern)

**Core principle: assert what's running, not what's queued.**

The 2026-04-29 and 2026-04-30 canary attempts both aborted on a `*.new`-presence rule. The first abort was a true positive (swap-glob bug had blocked the night's swap, leaving stale binaries running). The second was a false positive (operator legitimately staged the next day's deploy queue 44 minutes before the canary fired). The rule didn't distinguish.

The rewrite: **compute md5sum + stat size of the live binaries on the canary instance and assert against operator-supplied baseline values.** `.new` files in the directory become irrelevant — they only matter at the next swap, not at canary-execution time.

### Required pre-flight asserts (in this order)

1. **Process health.** `pgrep -f 'hlds_linux.*-port <PORT>'` returns a PID. Abort if not running.
2. **Most-recent restart entry exists with `Verification: 5/5`** (or `4/4` for Chicago).
   - `grep -E '<YYYY-MM-DD>.*03:0' ~/log/scheduled-restart.log | tail -10`
   - `grep -E '<YYYY-MM-DD>.*Verification: [0-9]+/[0-9]+ servers running' ~/log/scheduled-restart.log`
   - Confirms the swap actually ran. `5/5` (4/4 CHI) confirms all instances came back.
3. **Restart-script md5 matches operator-supplied baseline** (same sourcing rule as assert #4 — the operator provides the current fleet md5 at canary-creation time; `scripts/deploy-restart-script.py`'s Phase-1 consensus fetch prints it).
   - `md5sum ~/ktp-scheduled-restart.sh`
   - Detects regression of the swap script itself.
   - Do NOT hardcode the value in this runbook — the script changes with deploy waves (a stale pinned md5 false-aborted this assert against the 2026-07 R8-assert build; the old `02f49824…` pin predates it).
4. **Live-binary md5 matches operator-supplied baseline** for every canary-relevant plugin/binary.
   - `md5sum ~/dod-<PORT>/serverfiles/dod/addons/ktpamx/plugins/<X>.amxx`
   - This is the load-bearing assertion. The whole point.
   - The operator provides the expected md5 list at canary-creation time, sourced from the latest `CHANGES_SUMMARY_*.md` entry for the active deploy.
5. **Live-binary size matches expected** (belt + suspenders against md5 collision).
   - `stat -c '%s' <path>` per plugin.
6. **The variable being toggled is currently at the expected pre-toggle value.**
   - For a cvar canary: `grep -E '^\s*<cvar_name>' <cfg_path>` returns the pre-state.
   - Aborts if someone else got there first or if the variable is missing.

### Asserts NOT to use

- ❌ **`.new` file absence.** Legitimate next-day deploy queues trip this. Use live-binary md5/size instead.
- ❌ **"`.new` files staged within the last N hours" heuristic.** Same false-positive class, just delayed.
- ❌ **Plugin file-size only (no md5).** Two plugins of the same byte count won't trip a size check; an md5 will.
- ❌ **Process uptime > N hours.** Reasonable in principle, but the post-restart canary window is exactly when uptime is shortest. The Verification line is the cleaner signal.

### Abort handling

On any failed assertion: **report and stop.** No partial toggles, no "I'll do half of it." The canary is one variable; failing pre-flight means the baseline isn't where we think it is, and one more variable on top of an unknown baseline yields uninterpretable post-soak data.

---

## 3. Toggle execution pattern (cvar canary, cfg-persistent + runtime)

Once pre-flight passes, the toggle is a 4-step ssh sequence on the target host:

```bash
# 1. Backup the cfg before edit (timestamped — keep the path; rollback needs it)
TS=$(date +%Y%m%d-%H%M%S)
BAK=~/dod-<PORT>/serverfiles/dod/dodserver.cfg.bak-<reason>-${TS}
cp ~/dod-<PORT>/serverfiles/dod/dodserver.cfg "$BAK"

# 2. Persistent change: sed-edit cfg from current value to new value
sed -i 's/<cvar_name> "<old>"/<cvar_name> "<new>"/' ~/dod-<PORT>/serverfiles/dod/dodserver.cfg

# 3. Verify cfg shows new value
grep -E '^\s*<cvar_name>' ~/dod-<PORT>/serverfiles/dod/dodserver.cfg

# 4. Runtime change: LinuxGSM `send` writes to the tmux session of the running instance
# port_index = <PORT> - 27014 (so 27019 → dodserver5, 27015 → dodserver, etc.)
~/dod-<PORT>/dodserver<INDEX> send "<cvar_name> <new>"

# 5. Pause + capture console echo
sleep 3
tail -50 ~/dod-<PORT>/log/console/*-console.log | grep -i '<cvar_name>' | tail -5

# 6. Process still healthy
pgrep -af 'hlds_linux.*-port <PORT>' | head -2
```

**Persistence note:** the cfg sed-edit survives the next nightly restart — the swap script doesn't touch `dodserver.cfg`. So a canary toggled mid-day will remain in effect after the next 03:00 ET restart, no re-application needed.

---

## 4. Rollback

The backup path from step 1 is the rollback. Document it in the toggle's report:

```bash
cp <BAK_PATH> ~/dod-<PORT>/serverfiles/dod/dodserver.cfg
~/dod-<PORT>/dodserver<INDEX> send "<cvar_name> <old>"
```

If the canary survives long enough that you've forgotten the backup path: `ls -t ~/dod-<PORT>/serverfiles/dod/dodserver.cfg.bak-* | head -1`.

---

## 5. RemoteTrigger automation pattern

Canaries are typically scheduled via `RemoteTrigger create` with `run_once_at: "<UTC ISO8601>"`. The trigger body embeds the canary prompt. **Crib the structure from a recently-fired trigger** rather than writing JSON from scratch — the `job_config.ccr.events[].data.message.content` shape is deeply nested and easy to get wrong.

```python
# Get an existing trigger as a template
RemoteTrigger.get(trigger_id="<recent_canary_trigger>")
# Copy job_config + session_context verbatim
# Swap message.content + run_once_at + name
RemoteTrigger.create(body={...})
```

The agent prompt should:
1. Spell out the pre-flight assertions from §2 with concrete expected values for *this* canary.
2. Spell out the toggle commands from §3 with the specific ports/cvars/values.
3. Spell out the report format (markdown sections: pre-flight results, action taken, verification, backup path, rollback instructions, observation window).
4. Strict constraint: only modify the named instance. Don't restart anything. Don't push commits.

### Verifying a fired canary

`RemoteTrigger get <trigger_id>` after the fire time returns `enabled: false` + `ended_reason: run_once_fired` if the agent ran. **It does NOT return the agent's output** — for that, ssh to the target host and check ground truth:

```bash
# Did the toggle execute?
ls ~/dod-<PORT>/serverfiles/dod/dodserver.cfg.bak-<reason>-* 2>/dev/null   # backup file proves toggle ran
grep -E '^\s*<cvar_name>' ~/dod-<PORT>/serverfiles/dod/dodserver.cfg        # current cfg value
tail -200 ~/dod-<PORT>/log/console/*-console.log | grep -i '<cvar_name>'    # runtime echo
```

If `ended_reason: run_once_fired` but no backup file exists, the agent ran and aborted at pre-flight — diagnose which assertion fired (re-run §2's checks manually).

---

## 6. Known false-positive patterns (avoid these)

### `.new`-presence false positive (2026-04-30)

**Symptom:** canary aborts on `NEW_PLUGIN_PRESENT` despite live binaries being correct (md5/size match expected).
**Cause:** operator pre-staged the next nightly swap's `.new` files between the most recent restart and the canary fire time.
**Fix:** drop the `.new` rule per §2. Use live-binary md5/size instead.

### Stale-binary true positive masquerading as false positive (2026-04-29)

**Symptom:** canary aborts on `NEW_PLUGIN_PRESENT`, AND the live binary md5/size differs from the latest deploy expected values.
**Cause:** the swap script silently failed (e.g. swap-glob drift, unconsumed `.new` files post-restart). This is NOT a false positive — the canary correctly refused to add a variable to a broken baseline.
**Fix:** diagnose the swap failure, not the canary rule. The live-binary md5 assertion in §2 catches this directly.

### Rapid re-fire of fired trigger

**Symptom:** `RemoteTrigger get` shows `next_run_at` in the future even after `ended_reason: run_once_fired`.
**Cause:** harmless. `next_run_at` reflects what the trigger *would* fire next if re-enabled. `enabled: false` is the gate. Ignore `next_run_at` for one-shot canaries.

### LinuxGSM `send` echoing nothing

**Symptom:** `~/dod-<PORT>/dodserver<INDEX> send "<cvar> <value>"` returns `[ OK ]` but no echo appears in the console log.
**Cause:** usually the cvar name is misspelled or the cvar requires `;` terminator on this build. Check `tail -100 ~/dod-<PORT>/log/console/*-console.log` for an `Unknown command` line.
**Fix:** corrected name + retry. The cfg edit from step 2 is harmless if untouched by step 4.

---

## 7. Cross-references

- TODO: `HPAK crash — canary ACTIVE on ATL:27019` (the active canary this runbook codified).
- TODO: `Canary pre-flight rule rewrite — drop .new-presence abort` (the work item this runbook closes).
- Memory: `swap_script_globs_drift_2026-04-29.md` (the legitimate-bug case the original `.new` rule was designed for — still detected by §2's live-binary assertion).
- Memory: `linuxgsm_send_runtime_command.md` (the `dodserver{N} send` pattern step 4 uses).
- `KERNEL_EXPERIMENT_RUNBOOK.md` — sibling runbook for kernel-cmdline experiments, which use a different pattern (host-level reboot, multi-instance impact).
