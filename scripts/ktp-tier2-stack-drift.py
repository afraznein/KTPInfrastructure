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

THREE COMPARISONS, because one invariant does not fit every artifact:

  STACK + STRICT PLUGINS — md5 against the fleet. Byte-equality is the whole
  requirement, so any difference is drift.

  TEST-MODE PLUGINS — the DECLARED VERSION, decoded from both artifacts
  (amxx_version.py), compared directionally. These are built with
  KTP_TEST_MODE or rebuilt per run from upstream, so byte-equality with the
  fleet is WRONG for them and md5 says nothing. This used to be an mtime lag
  instead, and mtime is not the property anyone cares about: on 2026-09-28
  the fleet's KTPPracticeMode had been re-copied by a routine redistribute,
  moving its mtime 17 days without changing a line of source, and this
  checker had been reporting "restage it" every six hours for days about a
  runner holding the same 1.4.9 the fleet and origin/main both held. An
  alert that fires on a copy trains people to skim the one that fires on a
  regression. Version is the property; mtime rides along in the message as
  context only, and never triggers.

  Runner AHEAD of the fleet is not drift. A pre-activation gate is supposed
  to lead, and KTPHudObserver is rebuilt from upstream master on every run,
  so it leads the fleet routinely and correctly.

  CONFIGS — md5 against the fleet, enumerated FROM THE FLEET rather than from
  a list here, minus a named runner-local allowlist. Enumerating is the point:
  a hardcoded list cannot see a config the fleet ADDS, and that is how the
  runner ended up with no dodx.ini at all. ktp_maps.ini feeds match-handler
  map handling and had been 60 days behind the fleet, invisible to everything.
  sync-runner-stack.py writes this same set from this same allowlist, so a
  config alert here has a tool that clears it (a config the runner LACKS
  needs its --add-missing-configs).

⛔ hud_observer.cfg is ABSENT ON PURPOSE and its absence is CORRECT. It holds
the live HUD ingest URL and key; restoring it points the test harness at the
real ingest. It is in CONFIGS_RUNNER_LOCAL for that reason, not by oversight —
an automated sweep has already tried to "fix" it once.

Invoked by ktp-tier2-heartbeat.sh via the ktp-profile-aggregator venv (for
paramiko) with the aggregator's .env sourced (GAME_SSH_USER/GAME_SSH_PASSWORD).

Install (on the data server) — BOTH files, or the version check cannot run:
  sudo cp scripts/ktp-tier2-stack-drift.py scripts/amxx_version.py /usr/local/bin/

Exit codes: 0 = in sync, 1 = drift (detail on stdout), 2 = check failed
(SSH/env error, or a comparison that could not be made — callers should log,
not alert; a transient failure must not flap the drift state).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import time

try:
    import paramiko
except ImportError:
    print("paramiko not available — run via the ktp-profile-aggregator venv")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_amxx_version():
    """The version decoder, loaded from beside this script.

    A compiled .amxx is an XXMA container holding a zlib-compressed AMX image
    and Pawn stores strings one char per 32-bit cell, so `strings`/`grep` find
    nothing and return a confident zero. Decoding is the only honest read.

    Deployment note: this script is installed standalone into /usr/local/bin,
    so amxx_version.py must be copied there too (see the install block below).
    A missing decoder makes the version comparison INCONCLUSIVE, never green —
    the one outcome that would reintroduce the gap this check exists to close.
    """
    path = os.path.join(HERE, "amxx_version.py")
    spec = importlib.util.spec_from_file_location("_ktp_amxx_version", path)
    if spec is None or spec.loader is None:
        return None
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 — any load failure is "cannot check"
        return None
    return mod


AMXX_VERSION = _load_amxx_version()

RUNNER_TREE = os.environ.get("KTP_TIER2_TREE", "/opt/ktp-tier2-runner/serverfiles")
REF_HOST = os.environ.get("KTP_DRIFT_REF_HOST", "74.91.121.9")  # Atlanta bm
REF_TREE = os.environ.get("KTP_DRIFT_REF_TREE", "dod-27015/serverfiles")
SSH_USER = os.environ.get("GAME_SSH_USER", "dodserver")
SSH_PASSWORD = os.environ.get("GAME_SSH_PASSWORD", "")
DRIFT_STATE_PATH = os.environ.get("KTP_TIER2_DRIFT_STATE", "/var/lib/ktp-tier2-stack-drift.state.json")

# Paths relative to the serverfiles root.
#
# ⚠️ This list used to carry the comment "the per-run-recompiled plugins are
# deliberately NOT here — they can't drift." That premise was false and the
# exclusion built on it hid a real staleness for 13 days: the workflow does
# NOT recompile anything. tier2-integration.yml only `test -f`s pre-staged
# artifacts (the sole amxxpc call in the repo is in smoke-callable.yml, the
# per-repo Tier-1 smoke). Measured 2026-08-03: the runner's KTPMatchHandler
# was two versions behind the built artifact, and nothing alerted, because
# this checker had been told plugins were self-refreshing. Plugins are now
# checked — see PLUGINS_STRICT / PLUGINS_TESTMODE below — and so are configs,
# which carried the same 'runner-specific, cannot drift' premise and the same
# hole: ktp_maps.ini sat 60 days behind the fleet feeding match-handler map
# handling, and dodx.ini was simply never copied across at all.
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
    "dod/addons/ktpamx/plugins/admin.amxx",
    "dod/addons/ktpamx/plugins/stats_logging.amxx",
    "dod/addons/ktpamx/plugins/KTPAdminAudit.amxx",
    "dod/addons/ktpamx/plugins/ktp_cvar.amxx",
    "dod/addons/ktpamx/plugins/ktp_file.amxx",
    "dod/addons/ktpamx/plugins/KTPGrenadeDamage.amxx",
    "dod/addons/ktpamx/plugins/KTPGrenadeLoadout.amxx",
    "dod/addons/ktpamx/plugins/KTPHLTVRecorder.amxx",
    "dod/addons/ktpamx/plugins/KTPScoreTracker.amxx",
]

# Plugins whose bytes are SUPPOSED to differ from the fleet's: KTP_TEST_MODE
# builds, and the ones this repo's workflow rebuilds per run. md5 says nothing
# about these, so the comparison is the declared version and the direction is
# asymmetric — behind the fleet is drift, ahead of it is not.
#
# ⚠️ Scope, stated honestly: this catches runner-behind-FLEET. It would NOT have
# caught the 2026-08-03 case, where the runner held a build two versions behind
# the reviewed artifact about to be waved, because those versions were built and
# never staged anywhere. "Is the runner current?" at wave time is a different
# question from "has the runner fallen behind the fleet", and only the second is
# answerable from here — the first belongs in stage-wave.py as a pre-stage gate.
# Do not read a green result here as "the runner is ready to gate a wave."
#
# KTPWitness is deliberately absent: it is test-only and has no fleet counterpart
# at all, so there is nothing here to compare it against. Its source lives in this
# repo, so tier2-integration.yml builds it per run instead — staleness made
# impossible beats staleness detected.
PLUGINS_TESTMODE = [
    "dod/addons/ktpamx/plugins/KTPMatchHandler.amxx",
    "dod/addons/ktpamx/plugins/KTPPracticeMode.amxx",
    "dod/addons/ktpamx/plugins/KTPHudObserver.amxx",
]

CONFIG_DIR = "dod/addons/ktpamx/configs"

# Configs that are runner-local ON PURPOSE. Everything else in CONFIG_DIR is
# enumerated from the fleet and md5-compared, so a config the fleet gains later
# is covered without anyone editing this file. Each entry needs a reason; an
# unexplained exemption is how a real staleness gets parked here forever.
# sync-runner-stack.py never writes anything named here.
CONFIGS_RUNNER_LOCAL = {
    # ⛔ ABSENT ON PURPOSE, and its absence is CORRECT — not an oversight to fix.
    # It carries the live HUD ingest URL and key; restoring it points the test
    # harness at the real ingest with the real key.
    "hud_observer.cfg": "absent on purpose — live HUD ingest URL + key",
    "ac.ini": "test stub; the suite rewrites it per run",
    "discord.ini": "test stub; the fleet's holds live relay creds",
    "hltv_recorder.ini": "holds the HLTV API key; the runner has no HLTV pair",
    # Identical to the fleet's but for one line, so mirroring it to silence this
    # check would park a production credential in the CI tree permanently.
    "ktp.ini": "holds the live season match password; the harness needs its own",
    "ktp_ac_bans.ini": "live ban list, irrelevant to the harness and always moving",
    "users.ini": "admin credentials; the harness needs its own",
    # The runner loads KTPWitness, which must never appear on a fleet instance.
    "plugins.ini": "structurally runner-local — it loads the test-only witness",
    "sql.cfg": "DB credentials; mirroring would demand the runner hold the fleet's",
}

# Backups and hand-kept copies sitting in the same directory. A name-shaped
# filter, not an extension one: the estate's convention puts the marker at the
# END and separates it with either a dot or a hyphen -- `plugins.ini.bak-2026…`,
# `ktp_maps.ini.pre069`, `hud_observer.cfg.prod-stale-bak`. An extension-based
# filter lets all three through.
_CONFIG_IGNORE = re.compile(
    r"[.-](bak|backup|old|orig|tmp|pre|retired|disabled|stale)\w*", re.I)


def is_config_backup(name: str) -> bool:
    return bool(_CONFIG_IGNORE.search(name))


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """Orderable form of a declared plugin version, or None if it cannot be ordered.

    None is never treated as equal or as drift — it makes the comparison
    inconclusive and says so. A version we cannot read is not evidence about
    the runner in either direction.
    """
    if not text:
        return None
    m = re.match(r"^(\d+(?:\.\d+)*)", text.strip())
    if not m:
        return None
    return tuple(int(part) for part in m.group(1).split("."))


def version_is_behind(runner: str | None, fleet: str | None) -> bool | None:
    """True if the runner is behind the fleet, False if level or ahead, None if
    the pair cannot be ordered."""
    rv, fv = parse_version(runner), parse_version(fleet)
    if rv is None or fv is None:
        return None
    width = max(len(rv), len(fv))
    rv = rv + (0,) * (width - len(rv))
    fv = fv + (0,) * (width - len(fv))
    return rv < fv


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


def compute_drift(
    hashed: list[str],
    testmode: list[str],
    fleet_md5: dict[str, str],
    fleet_version: dict[str, str],
    runner_tree: str,
    ref_host: str,
    md5_fn=local_md5,
    exists_fn=os.path.exists,
    version_fn=None,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Compare runner vs fleet. Returns (drift_items, errors).

    Each drift item is (path, message, signature) — signature identifies the
    SPECIFIC mismatch (e.g. "runner_md5:fleet_md5"), not just the path, so a
    runner that re-syncs to a still-wrong value is treated as a fresh drift
    rather than a continuation of the old one.

    `hashed` is compared byte-for-byte. `testmode` is compared by declared
    version and only reports the runner being BEHIND: a runner that leads the
    fleet is a pre-activation gate or an upstream rebuild, both correct.
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

    for p in testmode:
        if p not in fleet_version:
            errors.append(f"{p}: no version readable on reference host {ref_host}")
            continue
        local_path = os.path.join(runner_tree, p)
        if not exists_fn(local_path):
            drifts.append((p, f"{p}: missing on runner", "missing"))
            continue
        runner_v = version_fn(local_path) if version_fn else None
        fleet_v = fleet_version[p]
        behind = version_is_behind(runner_v, fleet_v)
        if behind is None:
            # Inconclusive is its own outcome. Calling it green would restore the
            # blind spot; calling it drift would page on a version string nobody
            # can order.
            errors.append(
                f"{p}: cannot order versions (runner {runner_v or '?'} vs fleet {fleet_v or '?'})"
            )
            continue
        if behind:
            msg = (
                f"{p}: runner holds {runner_v}, fleet runs {fleet_v} "
                f"(test-mode build — md5 cannot be compared; restage it)"
            )
            drifts.append((p, msg, f"{runner_v}:{fleet_v}"))

    return drifts, errors


def compute_config_drift(
    fleet_md5: dict[str, str],
    runner_tree: str,
    config_dir: str,
    runner_local: dict[str, str],
    md5_fn=local_md5,
    exists_fn=os.path.exists,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Configs the runner should mirror, enumerated from the fleet.

    `fleet_md5` is keyed on BASENAME and is the fleet's whole configs directory
    minus backups; the runner-local allowlist is subtracted here rather than at
    the listing, so a file moving into or out of the allowlist is one edit in
    one place. A config the fleet has and the runner does not is drift, not an
    error: unlike a binary, a config the harness is simply missing changes what
    the suite exercises (dodx.ini was absent for weeks).
    """
    drifts: list[tuple[str, str, str]] = []
    errors: list[str] = []
    for name in sorted(fleet_md5):
        if name in runner_local:
            continue
        rel = f"{config_dir}/{name}"
        local_path = os.path.join(runner_tree, config_dir, name)
        if not exists_fn(local_path):
            drifts.append((rel, f"{rel}: on the fleet, absent on the runner", "missing"))
            continue
        lm = md5_fn(local_path)
        if lm != fleet_md5[name]:
            sig = f"{lm}:{fleet_md5[name]}"
            drifts.append((rel, f"{rel}: runner {lm[:8]}… vs fleet {fleet_md5[name][:8]}…", sig))
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


def runner_version(path: str) -> str | None:
    """Declared version of an artifact on the runner, decoded from its bytes."""
    if AMXX_VERSION is None:
        return None
    return AMXX_VERSION.extract_for_basename(path, os.path.basename(path))


def fetch_fleet_versions(sftp, ref_root: str, paths: list[str]) -> dict[str, str]:
    """Decode each test-mode plugin's version off the reference instance.

    Pulled rather than decoded remotely: the reference host runs the game, not
    our tooling, and shipping a decoder there to answer a monitoring question
    would put a second copy of it somewhere nobody updates.
    """
    out: dict[str, str] = {}
    for rel in paths:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".amxx")
        tmp.close()
        try:
            sftp.get(f"{ref_root}/{rel}", tmp.name)
            v = AMXX_VERSION.extract_for_basename(tmp.name, os.path.basename(rel))
            if v:
                out[rel] = v
        except Exception:  # noqa: BLE001 — a path we cannot read is left absent
            pass                                  # and surfaces as an error, not as green
        finally:
            os.unlink(tmp.name)
    return out


def fetch_fleet_configs(ssh, ref_root: str) -> dict[str, str]:
    """md5 of every non-backup config on the reference, keyed on basename.

    Enumerated from the fleet on purpose: a list here could not see a config
    the fleet gains, which is exactly how dodx.ini went uncopied.
    """
    _, out, _ = ssh.exec_command(
        f"cd '{ref_root}/{CONFIG_DIR}' && md5sum * 2>/dev/null", timeout=60)
    got: dict[str, str] = {}
    for line in out.read().decode(errors="replace").splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        name = parts[1].strip()
        if is_config_backup(name):
            continue
        got[name] = parts[0].lower()
    return got


def main() -> int:
    if not SSH_PASSWORD:
        print("GAME_SSH_PASSWORD not set — source the aggregator .env")
        return 2
    if AMXX_VERSION is None:
        # Never green on a decoder we could not load: the test-mode plugins would
        # silently stop being checked, which is the gap this exists to close.
        print("amxx_version.py not importable from beside this script — the "
              "test-mode plugin check cannot run. Copy it to the same directory "
              "(see the install block in this file's docstring).")
        return 2

    hashed = STACK_FILES + PLUGINS_STRICT
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(REF_HOST, username=SSH_USER, password=SSH_PASSWORD,
                    timeout=15, banner_timeout=15)
        _, hout, _ = ssh.exec_command("echo $HOME", timeout=30)
        ref_root = hout.read().decode(errors="replace").strip()
        if not ref_root.startswith("/"):
            ssh.close()
            print(f"could not resolve the reference user's home directory (got {ref_root!r})")
            return 2
        ref_root = f"{ref_root}/{REF_TREE}"

        cmd = "md5sum " + " ".join(f"'{ref_root}/{p}'" for p in hashed)
        _, out, _ = ssh.exec_command(cmd, timeout=60)
        raw = out.read().decode(errors="replace")

        sftp = ssh.open_sftp()
        try:
            fleet_version = fetch_fleet_versions(sftp, ref_root, PLUGINS_TESTMODE)
        finally:
            sftp.close()
        fleet_configs = fetch_fleet_configs(ssh, ref_root)
        ssh.close()
    except Exception as exc:  # noqa: BLE001 — any SSH failure = "can't check", not "drift"
        print(f"reference-host check failed: {type(exc).__name__}: {exc}")
        return 2

    if not fleet_configs:
        # An empty listing is a failed probe, not a fleet with no configs. The
        # positive control is that the reference certainly has amxx.cfg.
        print(f"no configs enumerated on {REF_HOST} — the listing failed; not reporting drift")
        return 2

    fleet_md5 = parse_md5sum(raw, hashed)

    drift_items, errors = compute_drift(
        hashed, PLUGINS_TESTMODE, fleet_md5, fleet_version,
        RUNNER_TREE, REF_HOST, version_fn=runner_version,
    )
    cfg_items, cfg_errors = compute_config_drift(
        fleet_configs, RUNNER_TREE, CONFIG_DIR, CONFIGS_RUNNER_LOCAL,
    )
    drift_items += cfg_items
    errors += cfg_errors

    checked = (len(hashed) + len(PLUGINS_TESTMODE)
               + len([n for n in fleet_configs if n not in CONFIGS_RUNNER_LOCAL]))
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
