#!/usr/bin/env python3
"""Run a fleet script with the project's credential and version rows wired in.

WHY THIS EXISTS. `stage-wave.py` is the standard way to push a wave, and on a
workstation it cannot be run as documented. It resolves the dodserver credential
from `$KTP_FLEET_SSH_PASSWORD`, else `~/.ktp_fleet_ssh_password` -- and on the
operator box neither exists, because the project's own rule is that credentials
reach a tool through a child process's environment and never through a command
line or a file on disk. `ktp_hosts.py` is the single source of truth and the
scripts here cannot import it unconditionally: it lives in the project root,
outside this repo, and holds live values.

So every wave has been staged by hand-writing a throwaway shim that imports
`ktp_hosts`, builds a child environment and execs the real tool. That shim was
rewritten from memory each time, lived in a temp directory, and was therefore
outside this repo, outside review and outside the freshness guard -- for the one
command in the stack that writes to all 24 production instances. The gap was not
the tool; it was that the documented way to invoke it was undocumented.

This is that shim, once, in the repo.

WHAT IT DOES NOT DO. It adds no deploy logic and makes no connection of its own.
It resolves two environment variables and execs a sibling. Every gate -- the
attribution check, the md5 pins, --pull-live, the row-flip gate, the activation-day
gate -- belongs to the script being run and is untouched.

THE GUARD STILL GOVERNS. `scripts/ktp_script_freshness.py` refuses to run a fleet
script whose bytes differ from `origin/main`, and the script this execs is a
SIBLING in the same checkout -- so a stale copy here cannot launder a stale copy
there. A second guard is deliberately not added: it would be a second thing to
misfire in front of the one that already works. What IS enforced is that the
override variables are never forwarded (GUARD_OVERRIDES below). A wrapper that
passed KTP_FRESHNESS_BYPASS through would turn the guard into decoration, and
doing it accidentally is exactly what a convenience script invites.

USAGE
  run-fleet-script.py <script> [args...]       # args pass through verbatim
  run-fleet-script.py --list                   # what may be run

  # a wave, with every gate the standard path carries
  run-fleet-script.py stage-wave.py --pull-live <dir> \
      -f <path> --expect <name>=<md5> --base <name>=<owner/repo@sha> \
      --row-version <name>=<version>

ENVIRONMENT
  KTP_FLEET_SSH_PASSWORD   honoured if already set; else imported from
                           <project>/ktp_hosts.py and passed to the child only
  KTP_FLEET_SSH_KEY        passed through untouched -- it selects a per-person key
                           and the child prefers it over any password
  KTP_CLAUDE_MD            version rows; defaults to <project>/.claude/skills/
                           fleet-versions/SKILL.md. stage-wave.py has no
                           --claude-md flag, so this is the only way to point it
  KTP_HOSTS_DIR            where ktp_hosts.py lives. REQUIRED from a worktree:
                           fleet scripts must run from a detached worktree at
                           origin/main, and a worktree on another drive has no
                           project root above it -- the default then resolves to
                           a directory holding neither the rows nor ktp_hosts.py.
                           Same variable the KTPDoDServerConfig shim uses

Exit code is the child's, unchanged. 2 means this script would not start it.
"""
from __future__ import annotations

import os
import subprocess
import sys

# Only scripts that genuinely need the fleet credential or the rows. An allowlist
# rather than "anything in scripts/": this runs with a live credential in its
# environment, so what it may hand that to is worth stating explicitly.
RUNNABLE = (
    "stage-wave.py",
    "deploy-to-fleet.py",
    "ktp-verify-deploy.py",
    "ktp-wave-ledger.py",
    "sync-runner-stack.py",
)

# Never forwarded: each one loosens the guard the child runs behind. Same list as
# ktp-wave-sweep.py, for the same reason.
GUARD_OVERRIDES = (
    "KTP_FRESHNESS_BYPASS",
    "KTP_FRESHNESS_OFFLINE",
    "KTP_FRESHNESS_REPO",
    "KTP_FRESHNESS_REF",
)


def project_root() -> str:
    # Normally this copy sits in <project>/scripts/, next to the rows and
    # ktp_hosts.py. From a worktree it does not -- and a worktree is the mandated
    # way to run a fleet script, so the override is the common case, not the
    # exotic one.
    override = os.environ.get("KTP_HOSTS_DIR", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def scripts_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def child_env(name: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in GUARD_OVERRIDES}
    dropped = [k for k in GUARD_OVERRIDES if k in os.environ]
    if dropped:
        # Say so: a silently-dropped override reads as the guard having passed.
        print("not forwarding %s -- the child's freshness guard is not this "
              "script's to relax" % ", ".join(dropped), file=sys.stderr)

    rows = env.get("KTP_CLAUDE_MD")
    if not rows:
        rows = os.path.join(project_root(), ".claude", "skills",
                            "fleet-versions", "SKILL.md")
        env["KTP_CLAUDE_MD"] = rows
    if not os.path.exists(rows):
        raise SystemExit("version rows not found at %s -- the row-flip gate cannot "
                         "read them, and it would report that as a failure to look "
                         "rather than as a missing file. Set $KTP_CLAUDE_MD." % rows)

    # A key beats a password in the child, so do not import a credential it will
    # not use: the import is the only step that touches live values.
    if env.get("KTP_FLEET_SSH_KEY", "").strip():
        return env
    if env.get("KTP_FLEET_SSH_PASSWORD"):
        return env

    root = project_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import ktp_hosts                      # the single source of truth
    except ImportError as exc:
        raise SystemExit(
            "cannot import ktp_hosts from %s for the fleet credential (%s).\n"
            "Set $KTP_FLEET_SSH_KEY or $KTP_FLEET_SSH_PASSWORD instead, or run "
            "this from a checkout that sits inside the project root." % (root, exc))
    try:
        env["KTP_FLEET_SSH_PASSWORD"] = ktp_hosts.FLEET_SSH_PASSWORD
    except AttributeError as exc:
        raise SystemExit("ktp_hosts has no FLEET_SSH_PASSWORD (%s) -- a renamed "
                         "attribute surfaces downstream as AuthenticationException, "
                         "which reads like a host problem." % exc)
    return env


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--list":
        for n in RUNNABLE:
            print(n)
        return 0

    name = os.path.basename(argv[0])
    if name not in RUNNABLE:
        raise SystemExit("%s is not in this script's allowlist. It runs with a live "
                         "fleet credential in its environment, so the list is "
                         "explicit: %s" % (name, ", ".join(RUNNABLE)))
    target = os.path.join(scripts_dir(), name)
    if not os.path.isfile(target):
        raise SystemExit("%s is allowlisted but not present at %s" % (name, target))

    env = child_env(name)
    # Everything but the credential, so a transcript shows what was run.
    print("script: %s" % target)
    print("rows:   %s" % env["KTP_CLAUDE_MD"])
    print("creds:  %s set in child env, value not shown"
          % ("KTP_FLEET_SSH_KEY" if env.get("KTP_FLEET_SSH_KEY", "").strip()
             else "KTP_FLEET_SSH_PASSWORD"))
    print("-" * 70)
    sys.stdout.flush()
    return subprocess.call([sys.executable, target] + argv[1:], env=env)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
