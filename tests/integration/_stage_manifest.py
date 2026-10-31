"""Resolve "which build is the runner holding?" from the stage manifest.

The version pin used to be a literal in each test (`... or "0.10.147"`), bumped
by hand as a checklist step. It rotted on 2026-08-03: the runner sat two
versions behind the artifact about to be waved and every behaviour test still
passed, because the pin was the only thing that could have caught it.

`scripts/stage-runner.py` now records what it staged, so the pin can come from
the act of staging instead of from someone remembering. Resolution order:

  1. env override  — the pre-activation gate, where the runner deliberately
                     LEADS the fleet and the version under test is not yet the
                     version anywhere else. Must win.
  2. manifest      — what stage-runner.py last put on this runner.
  3. literal floor — kept so a runner with no manifest yet (or a workstation
                     running the suite by hand) still asserts *something*
                     rather than silently skipping the check.

⛔ This file used to say the version "cannot be read out of the compiled `.amxx`
(XXMA+zlib), which is why the stager has to write it down". That is false and
`scripts/stage-runner.py` corrected it on 2026-08-10: it cannot be read by
`strings`, which is where the belief came from, but inflating the container and
reading cell-form yields it directly, which is what `scripts/amxx_version.py`
does and what the stager now uses to DERIVE what it records. So the manifest is
provenance -- a durable record of what was staged, when and by whom -- and not
a workaround for an unreadable artifact. Keep it for the resolution order
above; do not re-justify it with the claim.

⚠️ `staged_md5()` is read by nothing in this repo, and that is the current
state rather than an oversight to fix blind. A suite assertion comparing
manifest to disk would be permanently red for most of what the manifest holds:
the Tier-2 workflow rebuilds the plugins it gates on every run (each baking a
fresh per-minute BUILD_TIME), and `sync-runner-stack.py` mirrors the stack files
from the fleet, whose record is the fleet. `stage-runner.py --show` is the one
place that comparison is made, and it classifies those two cases rather than
calling either drift. Before wiring this into a test, settle which artifacts are
left -- the manifest is their record and only theirs.
"""

from __future__ import annotations

import json
import os
import posixpath
from pathlib import Path

_TREE = os.environ.get("KTP_TIER2_TREE", "/opt/ktp-tier2-runner/serverfiles")
_DEFAULT_MANIFEST = posixpath.join(posixpath.dirname(_TREE), "stage-manifest.json")


def _load() -> dict:
    path = os.environ.get("KTP_TIER2_MANIFEST", _DEFAULT_MANIFEST)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        # Absent or unreadable is normal off-runner; a corrupt manifest must not
        # take the suite down, it just falls through to the literal floor.
        return {}
    return data if isinstance(data, dict) else {}


def expected_version(plugin_basename: str, env_var: str, floor: str) -> str:
    """Pin for `plugin_basename`, honouring the env override first.

    `or` not a get() default, deliberately: the workflow always SETS the env var,
    to '' on scheduled and PR runs, and `os.environ.get(k, default)` returns ''
    for a set-but-empty var — which would pin every non-gate run to the empty
    string and fail all of them.
    """
    override = os.environ.get(env_var) or ""
    if override:
        return override
    entry = _load().get(plugin_basename) or {}
    return entry.get("version") or floor


def staged_md5(plugin_basename: str) -> str | None:
    """md5 stage-runner.py recorded for this plugin, or None if unrecorded."""
    return (_load().get(plugin_basename) or {}).get("md5")


def as_tuple(version: str) -> tuple[int, ...]:
    """Comparable form of a dotted version.

    For gating a test on the capability its plugin gained in a known release —
    the runner mirrors the LIVE fleet, so a suite can legitimately be newer than
    the build it runs against. String comparison would rank "0.10.9" above
    "0.10.10", which is exactly the range this project lives in.
    """
    parts = []
    for part in (version or "").split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def source() -> str:
    """Where a pin came from — for test failure messages, so a drift failure
    says whether it is arguing with the manifest or with a hardcoded floor."""
    path = os.environ.get("KTP_TIER2_MANIFEST", _DEFAULT_MANIFEST)
    return path if Path(path).exists() else "(no manifest — using literal floor)"
