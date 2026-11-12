"""Classify the Tier-2 runner's stage manifest against what is on its disk.

Shared by `stage-runner.py --show/--check` (over SSH, from a workstation) and the
Tier-2 suite's own manifest test (on the runner, every run). It imports nothing
outside the standard library on purpose: the suite's venv has no paramiko, and
the drift checker this reads exits at import without it.

Two classes of artifact keep their record somewhere other than the manifest, so
a manifest/disk difference on them is the steady state, not a fault:

  * workflow-rebuilt -- tier2-integration.yml compiles and `install -D`s these
    every run, each baking a fresh per-minute BUILD_TIME.
  * fleet-mirrored   -- sync-runner-stack.py copies these from the fleet; their
    record is the fleet.

Everything else the manifest records is the manifest's alone, and a difference
there is unexplained.
"""

from __future__ import annotations

import ast
import hashlib
import os
import posixpath
import re

PLUGIN_DIR = "dod/addons/ktpamx/plugins"
MODULE_DIR = "dod/addons/ktpamx/modules"
DLLS_DIR = "dod/addons/ktpamx/dlls"

# The KTPAMXX core ships here, not in MODULE_DIR -- same "everything .so is a
# module" trap this file already hit once for dodx. ktp-tier2-stack-drift.py's
# STACK_FILES confirms the split path.
CORE_BASENAMES = {"ktpamx_i386.so"}

HERE = os.path.dirname(os.path.abspath(__file__))
TIER2_WORKFLOW = os.path.join(
    os.path.dirname(HERE), ".github", "workflows", "tier2-integration.yml"
)
DRIFT_CHECKER = os.path.join(HERE, "ktp-tier2-stack-drift.py")

# Only the install destination, never a path the workflow merely checks for: a
# pattern that also matched the `test -f` verify step would claim artifacts the
# workflow leaves alone, and suppress the one disagreement worth printing.
_WORKFLOW_INSTALL_RE = re.compile(
    r"install\s+-D\s+\S+\s*(?:\\\s*)?\s*\"?[^\"\s]*/(?:plugins|modules|dlls)/([A-Za-z0-9_.+-]+)"
)

# Kinds. The first group needs nobody's attention; the second does.
AGREE = "agree"
WORKFLOW = "workflow-rebuilt"
MIRROR = "fleet-mirror"
UNRECORDED_REBUILT = "unrecorded-workflow-rebuilt"
ABSENT_REBUILT = "absent-workflow-rebuilt"
DRIFT = "drift"
ABSENT = "absent"
UNRECORDED = "unrecorded"
UNKNOWN_WORKFLOW = "unclassifiable-workflow"
UNKNOWN_MIRROR = "unclassifiable-drift-checker"

UNEXPLAINED = frozenset({DRIFT, ABSENT, UNRECORDED, UNKNOWN_WORKFLOW, UNKNOWN_MIRROR})

_FLAG_TEXT = {
    AGREE: "",
    WORKFLOW: "  <-- rebuilt per run by the Tier-2 workflow; not the build the gate tests",
    MIRROR: "  <-- fleet mirror, synced by sync-runner-stack.py; this manifest is not its record",
    UNRECORDED_REBUILT: "  <-- no manifest record; the Tier-2 workflow installs it every run",
    ABSENT_REBUILT: "  <-- not on the runner (the Tier-2 workflow installs it at the next run)",
    DRIFT: "  <-- MANIFEST DISAGREES WITH DISK",
    ABSENT: "  <-- not on the runner",
    UNRECORDED: "  <-- no manifest record, and nothing else installs it",
    UNKNOWN_WORKFLOW: "  <-- MANIFEST DISAGREES WITH DISK (could not read the Tier-2 workflow)",
    UNKNOWN_MIRROR: "  <-- MANIFEST DISAGREES WITH DISK (could not read the drift checker)",
}


def artifact_dir(name: str) -> str:
    """Where an artifact lives, by kind.

    Every path used to be built from PLUGIN_DIR, so a .so was looked for among
    the plugins and reported ABSENT while present and correct.
    """
    if name in CORE_BASENAMES:
        return DLLS_DIR
    return MODULE_DIR if name.endswith(".so") else PLUGIN_DIR


def workflow_rebuilt(path=TIER2_WORKFLOW):
    """Artifacts the Tier-2 workflow compiles and installs itself, every run.

    Returns None when the workflow cannot be read -- which must stay distinct
    from "it rebuilds nothing", or an unreadable file would silence the flag.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    return {m.group(1) for m in _WORKFLOW_INSTALL_RE.finditer(text)}


def fleet_mirrored(path=DRIFT_CHECKER):
    """Artifacts `sync-runner-stack.py` mirrors from the fleet, by basename.

    Read out of the drift checker's STACK_FILES and PLUGINS_STRICT -- the lists
    the sync tool reads -- by parsing, not importing: that script exits at
    import without paramiko, which the suite's venv does not have. None when
    either list cannot be read, so an unreadable checker never reads as "it
    mirrors nothing".
    """
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=str(path))
    except (OSError, SyntaxError, ValueError):
        return None
    lists = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in ("STACK_FILES", "PLUGINS_STRICT"):
                try:
                    lists[target.id] = list(ast.literal_eval(node.value))
                except ValueError:
                    return None
    if set(lists) != {"STACK_FILES", "PLUGINS_STRICT"}:
        return None
    return {posixpath.basename(p) for p in lists["STACK_FILES"] + lists["PLUGINS_STRICT"]}


def classify(name, disk, manifest_md5, rebuilt, mirrored=frozenset()):
    """One artifact's manifest-vs-disk standing, as one of the kinds above.

    `disk` is an md5 or "ABSENT"; `manifest_md5` is "-" when unrecorded;
    `rebuilt`/`mirrored` are None when their source could not be read.
    """
    in_rebuilt = bool(rebuilt) and name in rebuilt
    if disk == "ABSENT":
        return ABSENT_REBUILT if in_rebuilt else ABSENT
    if manifest_md5 == "-":
        return UNRECORDED_REBUILT if in_rebuilt else UNRECORDED
    if disk == manifest_md5:
        return AGREE
    if rebuilt is None:
        return UNKNOWN_WORKFLOW
    # Workflow first: when a file is both, its bytes are whatever the last run
    # installed, so that is the honest thing to say about it.
    if in_rebuilt:
        return WORKFLOW
    if mirrored is None:
        return UNKNOWN_MIRROR
    if name in mirrored:
        return MIRROR
    return DRIFT


def flag_text(kind):
    return _FLAG_TEXT[kind]


def local_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_DERIVE = object()


def classify_local(tree, manifest, rebuilt=_DERIVE, mirrored=_DERIVE):
    """Classify every manifest entry against a tree on THIS filesystem.

    Returns [(name, kind, manifest_md5, disk_md5)]. Used by the suite, which
    runs on the runner and can read the files directly.
    """
    if rebuilt is _DERIVE:
        rebuilt = workflow_rebuilt()
    if mirrored is _DERIVE:
        mirrored = fleet_mirrored()
    rows = []
    for name in sorted(manifest):
        entry = manifest.get(name) or {}
        mmd5 = (entry.get("md5") or "-").lower() if isinstance(entry, dict) else "-"
        path = os.path.join(tree, artifact_dir(name), name)
        disk = local_md5(path) if os.path.isfile(path) else "ABSENT"
        rows.append((name, classify(name, disk, mmd5, rebuilt, mirrored), mmd5, disk))
    return rows
