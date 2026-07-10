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

Invoked by ktp-tier2-heartbeat.sh via the ktp-profile-aggregator venv (for
paramiko) with the aggregator's .env sourced (GAME_SSH_USER/GAME_SSH_PASSWORD).

Exit codes: 0 = in sync, 1 = drift (detail on stdout), 2 = check failed
(SSH/env error — callers should log, not alert; a transient failure must not
flap the drift state).
"""
from __future__ import annotations

import hashlib
import os
import sys

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

# Paths relative to the serverfiles root. The per-run-recompiled plugins are
# deliberately NOT here — they can't drift. Configs are runner-specific.
STACK_FILES = [
    "engine_i486.so",
    "hlds_linux",
    "libsteam_api.so",
    "dod/addons/ktpamx/dlls/ktpamx_i386.so",
    "dod/addons/ktpamx/modules/dodx_ktp_i386.so",
    "dod/addons/ktpamx/modules/reapi_ktp_i386.so",
    "dod/addons/ktpamx/modules/amxxcurl_ktp_i386.so",
]


def local_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not SSH_PASSWORD:
        print("GAME_SSH_PASSWORD not set — source the aggregator .env")
        return 2

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(REF_HOST, username=SSH_USER, password=SSH_PASSWORD,
                    timeout=15, banner_timeout=15)
        cmd = "md5sum " + " ".join(f"~/{REF_TREE}/{p}" for p in STACK_FILES)
        _, out, err = ssh.exec_command(cmd, timeout=60)
        raw = out.read().decode(errors="replace")
        ssh.close()
    except Exception as exc:  # noqa: BLE001 — any SSH failure = "can't check", not "drift"
        print(f"reference-host check failed: {type(exc).__name__}: {exc}")
        return 2

    fleet: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            # md5sum prints the expanded absolute path; match on our suffix.
            for p in STACK_FILES:
                if parts[1].strip().endswith(p):
                    fleet[p] = parts[0]

    drifts, errors = [], []
    for p in STACK_FILES:
        if p not in fleet:
            errors.append(f"{p}: missing on reference host {REF_HOST}")
            continue
        local_path = os.path.join(RUNNER_TREE, p)
        if not os.path.exists(local_path):
            drifts.append(f"{p}: missing on runner")
            continue
        lm = local_md5(local_path)
        if lm != fleet[p]:
            drifts.append(f"{p}: runner {lm[:8]}… vs fleet {fleet[p][:8]}…")

    if errors:
        print("; ".join(errors))
        return 2
    if drifts:
        print(f"runner stack drift vs {REF_HOST} ({len(drifts)} file(s)): " + "; ".join(drifts))
        return 1
    print(f"runner stack in sync with {REF_HOST} ({len(STACK_FILES)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
