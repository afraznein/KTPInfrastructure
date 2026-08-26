#!/usr/bin/env python3
"""ktp-tier2-stack-drift — is the Tier-2 runner's module stack fleet-accurate?

The runner's value depends on testing against the stack the fleet actually
runs ("module stack MUST track the fleet" — tier2-runner-architecture). That
rule was checklist-enforced only, and drifted silently between 2026-06-28 and
2026-07-10: the runner sat on a .926 engine, a never-shipped dev dodx and
amxxcurl 1.3.11 while green runs certified an environment that existed
nowhere. This makes the drift loud instead: md5-compare the runner's stack
binaries against a fleet reference instance.

Deliberate drift is fine (e.g. the runner leading the fleet by a few hours as
a pre-activation gate) — the caller (ktp-tier2-heartbeat.sh) alerts once on
the transition and once on recovery, not per run. This checker only reports.

⚠️ "Reports" used to mean a flat md5 diff with no sense of time. A fleet ABI
wave puts the runner behind the moment it activates — that is routine and
expected, not an incident — but the message read identically whether the
drift was six hours old or six weeks old, so every wave night paged like an
emergency and a genuinely neglected runner paged the same way. This checker
now tracks, per drifted path, how long it has been drifting (a small state
file keyed on the actual mismatch, not on the path alone — a runner that
re-syncs to a DIFFERENT wrong value still counts as newly drifted) and prints
that age. A human reading "drifting 3h" after a wave night can tell it apart
from "drifting 9d" without knowing the release calendar.

Invoked by ktp-tier2-heartbeat.sh via the ktp-profile-aggregator venv (for
paramiko) with the aggregator's .env sourced (GAME_SSH_USER/GAME_SSH_PASSWORD).

Exit codes: 0 = in sync, 1 = drift (detail on stdout), 2 = check failed
(SSH/env error — callers should log, not alert; a transient failure must not
flap the drift state).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

try:
    import paramiko
except ImportError:
    print("paramiko not available — run via the ktp-profile-aggregator venv")
    sys.exit(2)

RUNNER_TREE = os.environ.get("KTP_TIER2_TREE", "/opt/ktp-tier2-runner/serverfiles")
REF_HOST = os.environ.get("KTP_DRIFT_REF_HOST", "74.91.121.9")  # Atlanta bm
REF_TREE = os.environ.get("KTP_DRIFT_REF_TREE", "dod-27015/serverfiles")
SSH_USER = os.environ.get("GAME_SSH_USER", "dodserver")
SSH_PASSWORD = os.environ.get("GAME_SSH_PASSWORD", "")
DRIFT_STATE_PATH = os.environ.get("KTP_TIER2_DRIFT_STATE", "/var/lib/ktp-tier2-stack-drift.state.json")

# Paths relative to the serverfiles root. Configs are runner-specific.
#
# ⚠️ This list used to carry the comment "the per-run-recompiled plugins are
# deliberately NOT here — they can't drift." That premise was false and the
# exclusion built on it hid a real staleness for 13 days: the workflow does
# NOT recompile anything. tier2-integration.yml only `test -f`s pre-staged
# artifacts (the sole amxxpc call in the repo is in smoke-callable.yml, the
# per-repo Tier-1 smoke). Measured 2026-08-03: the runner's KTPMatchHandler
# was two versions behind the built artifact, and nothing alerted, because
# this checker had been told plugins were self-refreshing. Plugins are now
# checked — see PLUGINS_STRICT / PLUGINS_TESTMODE below.
STACK_FILES = [
    "engine_i486.so",
    "hlds_linux",
    "libsteam_api.so",
    "dod/addons/ktpamx/dlls/ktpamx_i386.so",
    "dod/addons/ktpamx/modules/dodx_ktp_i386.so",
    "dod/addons/ktpamx/modules/reapi_ktp_i386.so",
    "dod/addons/ktpamx/modules/amxxcurl_ktp_i386.so",
]

# Plugins the runner should hold BYTE-IDENTICAL to the fleet. A mismatch here
# is unambiguous drift.
PLUGINS_STRICT = [
    "dod/addons/ktpamx/plugins/KTPAdminAudit.amxx",
    "dod/addons/ktpamx/plugins/ktp_cvar.amxx",
    "dod/addons/ktpamx/plugins/ktp_file.amxx",
    "dod/addons/ktpamx/plugins/KTPGrenadeDamage.amxx",
    "dod/addons/ktpamx/plugins/KTPGrenadeLoadout.amxx",
    "dod/addons/ktpamx/plugins/KTPHLTVRecorder.amxx",
    "dod/addons/ktpamx/plugins/KTPScoreTracker.amxx",
]

# Plugins the runner runs as KTP_TEST_MODE builds. These are SUPPOSED to differ
# from the fleet byte-for-byte, so md5 says nothing. Compare mtime instead:
# if the fleet's copy is materially newer, the runner is testing an old build.
#
# ⚠️ Scope, stated honestly: this catches runner-behind-FLEET. It would NOT have
# caught the 2026-08-03 case, where the runner held a Jul 21 build and the fleet
# held Jul 20 — the runner was *newer* than the fleet by mtime, yet two versions
# behind the reviewed artifact about to be waved, because 0.10.148/149 were built
# and never staged anywhere. "Is the runner current?" at wave time is a different
# question from "has the runner fallen behind the fleet", and only the second one
# is answerable from here. The first belongs in stage-wave.py as a pre-stage gate
# (assert the runner holds the matching test-mode build before staging a plugin
# wave) — see TODO.md. Do not read a green result here as "the runner is ready
# to gate a wave."
PLUGINS_TESTMODE = [
    "dod/addons/ktpamx/plugins/KTPMatchHandler.amxx",
    "dod/addons/ktpamx/plugins/KTPPracticeMode.amxx",
]

# How much newer the fleet copy may be before we call the runner stale. A wave
# legitimately puts the fleet ahead for a few hours (stage → nightly activate →
# morning-after runner restage), so this must clear a normal wave without firing.
STALE_AFTER_SECONDS = int(os.environ.get("KTP_TIER2_PLUGIN_MAX_LAG", 3 * 86400))


def local_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_md5sum(raw: str, paths: list[str]) -> dict[str, str]:
    """md5sum prints the expanded absolute path; match on our suffix."""
    fleet: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            for p in paths:
                if parts[1].strip().endswith(p):
                    fleet[p] = parts[0]
    return fleet


def parse_mtime(raw: str, paths: list[str]) -> dict[str, int]:
    mtimes: dict[str, int] = {}
    for line in raw.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            for p in paths:
                if parts[1].strip().endswith(p):
                    mtimes[p] = int(parts[0])
    return mtimes


def compute_drift(
    hashed: list[str],
    testmode: list[str],
    fleet_md5: dict[str, str],
    fleet_mtime: dict[str, int],
    runner_tree: str,
    stale_after_seconds: int,
    ref_host: str,
    md5_fn=local_md5,
    exists_fn=os.path.exists,
    mtime_fn=os.path.getmtime,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Compare runner vs fleet. Returns (drift_items, errors).

    Each drift item is (path, message, signature) — signature identifies the
    SPECIFIC mismatch (e.g. "runner_md5:fleet_md5"), not just the path, so a
    runner that re-syncs to a still-wrong value is treated as a fresh drift
    rather than a continuation of the old one.
    """
    drifts: list[tuple[str, str, str]] = []
    errors: list[str] = []

    for p in hashed:
        if p not in fleet_md5:
            errors.append(f"{p}: missing on reference host {ref_host}")
            continue
        local_path = os.path.join(runner_tree, p)
        if not exists_fn(local_path):
            drifts.append((p, f"{p}: missing on runner", "missing"))
            continue
        lm = md5_fn(local_path)
        if lm != fleet_md5[p]:
            sig = f"{lm}:{fleet_md5[p]}"
            drifts.append((p, f"{p}: runner {lm[:8]}… vs fleet {fleet_md5[p][:8]}…", sig))

    # Test-mode plugins: md5 is meaningless (they're built with KTP_TEST_MODE),
    # so the question is only "has the runner fallen behind the fleet".
    for p in testmode:
        if p not in fleet_mtime:
            errors.append(f"{p}: missing on reference host {ref_host}")
            continue
        local_path = os.path.join(runner_tree, p)
        if not exists_fn(local_path):
            drifts.append((p, f"{p}: missing on runner", "missing"))
            continue
        local_mtime = int(mtime_fn(local_path))
        lag = fleet_mtime[p] - local_mtime
        if lag > stale_after_seconds:
            msg = (
                f"{p}: runner build is {lag // 86400}d older than the fleet's "
                f"(test-mode, so md5 can't be compared — restage it)"
            )
            sig = f"{local_mtime}:{fleet_mtime[p]}"
            drifts.append((p, msg, sig))

    return drifts, errors


def load_drift_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_drift_state(path: str, state: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError:
        pass  # age tracking is enrichment, not correctness — never fail the check over it


def update_drift_ages(prev_state: dict, drift_items: list[tuple[str, str, str]], now: int) -> dict:
    """Carry forward 'since' for paths whose signature is unchanged; start a
    fresh clock for anything new or whose mismatch changed shape. Paths no
    longer drifting are dropped, so a state file never reports on resolved
    drift."""
    new_state: dict = {}
    for path, _msg, sig in drift_items:
        prev = prev_state.get(path)
        if prev and prev.get("sig") == sig:
            new_state[path] = prev
        else:
            new_state[path] = {"sig": sig, "since": now}
    return new_state


def format_age(age_seconds: int) -> str:
    if age_seconds < 300:
        return "just started"
    if age_seconds < 3600:
        return f"drifting {age_seconds // 60}m"
    if age_seconds < 86400:
        return f"drifting {age_seconds // 3600}h"
    return f"drifting {age_seconds // 86400}d"


def annotate_drift(drift_items: list[tuple[str, str, str]], state: dict, now: int) -> list[str]:
    out = []
    for path, msg, _sig in drift_items:
        since = state.get(path, {}).get("since", now)
        out.append(f"{msg} [{format_age(now - since)}]")
    return out


def main() -> int:
    if not SSH_PASSWORD:
        print("GAME_SSH_PASSWORD not set — source the aggregator .env")
        return 2

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(REF_HOST, username=SSH_USER, password=SSH_PASSWORD,
                    timeout=15, banner_timeout=15)
        hashed = STACK_FILES + PLUGINS_STRICT
        cmd = "md5sum " + " ".join(f"~/{REF_TREE}/{p}" for p in hashed)
        _, out, err = ssh.exec_command(cmd, timeout=60)
        raw = out.read().decode(errors="replace")
        # mtimes for the test-mode plugins, which md5 cannot speak to.
        mcmd = "stat -c '%Y %n' " + " ".join(f"~/{REF_TREE}/{p}" for p in PLUGINS_TESTMODE)
        _, mout, _ = ssh.exec_command(mcmd, timeout=60)
        mraw = mout.read().decode(errors="replace")
        ssh.close()
    except Exception as exc:  # noqa: BLE001 — any SSH failure = "can't check", not "drift"
        print(f"reference-host check failed: {type(exc).__name__}: {exc}")
        return 2

    hashed = STACK_FILES + PLUGINS_STRICT
    fleet_md5 = parse_md5sum(raw, hashed)
    fleet_mtime = parse_mtime(mraw, PLUGINS_TESTMODE)

    drift_items, errors = compute_drift(
        hashed, PLUGINS_TESTMODE, fleet_md5, fleet_mtime,
        RUNNER_TREE, STALE_AFTER_SECONDS, REF_HOST,
    )

    checked = len(STACK_FILES) + len(PLUGINS_STRICT) + len(PLUGINS_TESTMODE)
    if errors:
        print("; ".join(errors))
        return 2
    if drift_items:
        now = int(time.time())
        prev_state = load_drift_state(DRIFT_STATE_PATH)
        state = update_drift_ages(prev_state, drift_items, now)
        save_drift_state(DRIFT_STATE_PATH, state)
        annotated = annotate_drift(drift_items, state, now)
        print(f"runner stack drift vs {REF_HOST} ({len(drift_items)} file(s)): " + "; ".join(annotated))
        return 1

    # Nothing drifting now — clear any stale state so a future drift starts
    # its clock from zero instead of inheriting a resolved one's age.
    if os.path.exists(DRIFT_STATE_PATH):
        save_drift_state(DRIFT_STATE_PATH, {})
    print(f"runner stack in sync with {REF_HOST} ({checked} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
