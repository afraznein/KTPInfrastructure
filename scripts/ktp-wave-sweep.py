#!/usr/bin/env python3
"""Run the fleet wave sweep from the operator workstation.

The systemd unit (systemd/ktp-wave-sweep.service) cannot do this: it expects the
version rows and the wave ledger on the data server, and both moved -- the rows
into the project's .claude/skills/fleet-versions, the ledger onto the
workstation. The workstation is the only host holding both inputs.

WHERE THE LEDGER RUNS FROM
ktp-wave-ledger.py refuses to run unless ktp_script_freshness.py can prove it is
origin/main, and that proof needs the running file to sit inside a git checkout
at the ref. The previous wrapper exported the blob to a temp directory, which is
by construction a copy of unknown provenance, so the guard refused every night.
This one keeps a dedicated clone, used for nothing else, and runs the ledger
inside it:

  1. clone it on first use (single branch, no tags);
  2. fetch origin main;
  3. refuse if any tracked file in it has been edited -- never discard the edit;
  4. check out origin/main detached, and assert HEAD and scripts/ match it;
  5. run scripts/ktp-wave-ledger.py sweep from that tree, with the guard intact.

The guard re-fetches and re-checks on its own; nothing here weakens it, and an
ambient KTP_FRESHNESS_BYPASS / _OFFLINE / _REPO is removed from the child's
environment so a scheduled run cannot inherit one.

Env (all optional):
  KTP_CLAUDE_MD            version rows (default <project>/.claude/skills/fleet-versions/SKILL.md)
  KTP_WAVE_SWEEP_TREE      the dedicated clone (default ~/.ktp/wave-sweep-tree)
  KTP_WAVE_SWEEP_REMOTE    clone URL (default the public KTPInfrastructure repo)
  KTP_WAVE_SWEEP_STATE     result record (default ~/.ktp/wave-sweep-state.json)
  KTP_FLEET_SSH_PASSWORD   else imported from <project>/ktp_hosts.py

Exit codes mirror the unit's, because the meanings are load-bearing:
  0  clean          every live pinned md5 is on its row
  1  finding        a row is stale, or a staged .new is in no pending wave
  2  could not look never a pass
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import sys

DEFAULT_REMOTE = "https://github.com/afraznein/KTPInfrastructure.git"
LEDGER = "scripts/ktp-wave-ledger.py"
# Never forwarded to the ledger: each one loosens the guard it runs behind.
GUARD_OVERRIDES = ("KTP_FRESHNESS_BYPASS", "KTP_FRESHNESS_OFFLINE", "KTP_FRESHNESS_REPO",
                   "KTP_FRESHNESS_REF")


def project_root() -> str:
    # The deployed copy sits in <project>/scripts/, next to the rows and ktp_hosts.py.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def state_path() -> str:
    return os.path.expanduser(os.environ.get("KTP_WAVE_SWEEP_STATE")
                              or os.path.join("~", ".ktp", "wave-sweep-state.json"))


class CouldNotLook(Exception):
    pass


def _record(rc: int, summary: str) -> None:
    # Alert on WORK DONE: this file's mtime is the proof the scheduled task ran.
    path = state_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"ran_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                       "rc": rc, "summary": summary[:2000]}, fh, indent=2)
    except OSError as exc:                       # never mask the sweep's own result
        print("warning: could not write %s (%s)" % (path, exc), file=sys.stderr)


def _git(tree: str | None, *args: str, timeout: int = 300) -> str:
    cmd = ["git"] + (["-C", tree] if tree else []) + list(args)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CouldNotLook("`%s` failed: %s" % (" ".join(cmd), exc))
    if p.returncode != 0:
        raise CouldNotLook("`%s` exited %d: %s" % (" ".join(cmd), p.returncode,
                                                   (p.stderr or p.stdout).strip()))
    return p.stdout.strip()


def prepare_tree(tree: str, remote: str) -> str:
    """Bring the dedicated clone to origin/main and prove it. Returns the commit."""
    if not os.path.exists(tree):
        os.makedirs(os.path.dirname(os.path.abspath(tree)), exist_ok=True)
        _git(None, "clone", "--quiet", "--single-branch", "--branch", "main", "--no-tags",
             remote, tree)
    top = _git(tree, "rev-parse", "--show-toplevel")
    if not os.path.samefile(top, tree):
        raise CouldNotLook("%s is not the top of its own checkout (%s is)" % (tree, top))
    url = _git(tree, "remote", "get-url", "origin")
    if url.rstrip("/") != remote.rstrip("/"):
        raise CouldNotLook("%s tracks %s, not %s" % (tree, url, remote))

    _git(tree, "fetch", "--quiet", "--no-tags", "origin", "main")
    dirty = _git(tree, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise CouldNotLook("tracked files in %s were edited, and this tree is the sweep's "
                           "alone -- not discarding them:\n%s" % (tree, dirty))
    _git(tree, "checkout", "--quiet", "--detach", "origin/main")

    head, ref = _git(tree, "rev-parse", "HEAD"), _git(tree, "rev-parse", "origin/main")
    if head != ref:
        raise CouldNotLook("%s is at %s after checkout, origin/main is %s" % (tree, head, ref))
    try:
        _git(tree, "diff", "--quiet", "origin/main", "--", "scripts/")
    except CouldNotLook:
        raise CouldNotLook("scripts/ in %s still differs from origin/main after checkout" % tree)
    if not os.path.isfile(os.path.join(tree, LEDGER)):
        raise CouldNotLook("origin/main has no %s" % LEDGER)
    return head


def child_env(rows: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in GUARD_OVERRIDES}
    env["KTP_CLAUDE_MD"] = rows
    if "KTP_FLEET_SSH_PASSWORD" not in env:
        sys.path.insert(0, project_root())
        try:
            import ktp_hosts                     # the single source of truth
        except ImportError as exc:
            raise CouldNotLook("cannot import ktp_hosts for the fleet credential (%s)" % exc)
        env["KTP_FLEET_SSH_PASSWORD"] = ktp_hosts.FLEET_SSH_PASSWORD
    return env


def main() -> int:
    rows = os.environ.get("KTP_CLAUDE_MD") or os.path.join(
        project_root(), ".claude", "skills", "fleet-versions", "SKILL.md")
    tree = os.path.expanduser(os.environ.get("KTP_WAVE_SWEEP_TREE")
                              or os.path.join("~", ".ktp", "wave-sweep-tree"))
    remote = os.environ.get("KTP_WAVE_SWEEP_REMOTE") or DEFAULT_REMOTE
    try:
        if not os.path.exists(rows):
            raise CouldNotLook("version rows not found at %s -- nothing to compare against" % rows)
        commit = prepare_tree(tree, remote)
        env = child_env(rows)
    except CouldNotLook as exc:
        msg = "could not look -- %s" % exc
        print("FATAL: %s" % msg, file=sys.stderr)
        _record(2, msg)
        return 2

    print("[wave-sweep] ledger from %s at %s" % (tree, commit[:12]), file=sys.stderr)
    proc = subprocess.run([sys.executable, os.path.join(tree, LEDGER), "sweep"],
                          cwd=tree, env=env, capture_output=True, text=True)
    out = (proc.stdout + proc.stderr).strip()
    print(out)

    # The contract above is 0/1/2 and downstream reads only those. A crash exits 1,
    # the code for "I looked and found drift", and a refusal exits 3. Neither looked
    # at the fleet, so neither may report a finding.
    rc = proc.returncode
    crashed = bool(re.search(r"^Traceback \(most recent call last\):", out, re.M))
    if rc not in (0, 1) or (rc == 1 and crashed):
        why = ("the ledger died before reading the fleet" if crashed
               else "the ledger refused to run, so nothing was read")
        out = ("could not look -- %s; reporting 2, not a finding "
               "(child exit was %d)\n\n%s" % (why, rc, out))
        rc = 2
        print(out.split("\n\n", 1)[0], file=sys.stderr)

    _record(rc, out)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
