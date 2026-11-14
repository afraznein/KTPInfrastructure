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
It resolves a credential pair and the version rows, and execs a sibling. Every gate -- the
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
  GAME_SSH_PASSWORD        the SAME fleet credential under the name
                           sync-runner-stack.py reads for its fleet-reference
                           connection. Derived from KTP_FLEET_SSH_PASSWORD rather
                           than imported twice -- see SSH_PASSWORD_ALIASES
  KTP_RCON_PASSWORD        honoured if already set; else imported from
                           ktp_hosts.py, and only for the one script that issues
                           rcon (NEEDS_RCON). Without it ktp-verify-deploy.py
                           refuses its --check-runtime leg, which is the whole
                           point of the leg: a runtime verify that quietly did
                           not happen reads as a fleet that passed one
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
import re
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

# Left out on purpose, with the reason the refusal prints. The unit tests check
# each reason against the script's own source, so a stale one fails.
NOT_RUNNABLE = {
    "stage-runner.py":
        "it reads neither the fleet credential nor the version rows, so this "
        "wrapper would only hand it a live password it never uses. Run it "
        "directly from the worktree with KTP_TIER2_SSH_HOST set; the data "
        "server is keys-only and paramiko finds the key itself",
    "ktp_script_freshness.py":
        "its reporting mode reads the KTP_FRESHNESS_* variables this wrapper "
        "strips, and it needs no credential. Run it directly: "
        "python scripts/ktp_script_freshness.py <path>",
    "ktp-install":
        "it imports fcntl, which is POSIX-only, so it cannot run on a Windows "
        "workstation at all. The real one is /usr/local/bin/ktp-install on the "
        "host it installs to",
}

# Who gets the rcon credential: the one script that issues rcon, and nothing else.
# A wrapper that holds a live value hands out as little of it as the job needs, and
# the four others have no reference to it at all. Narrower than RUNNABLE on purpose.
NEEDS_RCON = ("ktp-verify-deploy.py",)

# Children that read the fleet SSH credential under a DIFFERENT env name than the
# one exported above. sync-runner-stack.py's fleet-reference connection reads
# GAME_SSH_PASSWORD and is password-only (it passes no key), so a wrapper setting
# just KTP_FLEET_SSH_PASSWORD hands it an empty string -- and paramiko then raises
# "No authentication methods available", which reads like a host or key fault
# rather than a wiring one. It went unnoticed because nothing had run that script
# through here since it was allowlisted.
#
# This table alone would be the same kind of defect one layer up: a restated list
# that goes stale the next time a child picks a new name. unsatisfied_credentials()
# below is the part that does not rot -- it reads the child's own source.
SSH_PASSWORD_ALIASES = {
    "sync-runner-stack.py": ("GAME_SSH_PASSWORD",),
}

# Credential names an allowlisted child reads that this wrapper deliberately does
# NOT set, each with the reason it is fine. Anything a child reads that is not here
# and not supplied is a wiring gap, and tests/unit/test_run_fleet_script.py fails
# until someone either supplies it or writes down why they did not. That decision
# point is the actual fix: the GAME_SSH_PASSWORD gap survived because nothing ever
# had to account for the difference between the names set and the names read.
KNOWN_UNSATISFIED = {
    "KTP_TIER2_SSH_PASSWORD":
        "the data server is keys-only, so KTP_TIER2_SSH_KEY carries a key PATH "
        "instead; a password there would fail even if it were supplied",
}

# Credential-shaped env names, read out of a child's source rather than listed.
CREDENTIAL_NAME = re.compile(
    r'''(?:os\.environ(?:\.get\(|\[)|os\.getenv\()["']'''
    r'''([A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|RCON)[A-Z0-9_]*)["']'''
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


def propagate_ssh_aliases(env: dict, aliases: tuple) -> None:
    """One resolved value under every name the child reads.

    A copy, never a second import: the import is the only step that touches live
    values, so an alias satisfiable from what is already in the environment must
    not trigger one. That is also why this is called on the no-import path.
    """
    resolved = env.get("KTP_FLEET_SSH_PASSWORD")
    if not resolved:
        return
    for alias in aliases:
        if not env.get(alias):
            env[alias] = resolved


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
    # The exception is a child whose own connection takes a password and no key --
    # for that one a configured key is not an alternative, so the password is still
    # needed. Keying this off the alias table rather than the script name keeps the
    # two facts about such a child in one place.
    aliases = SSH_PASSWORD_ALIASES.get(name, ())
    want_ssh = not env.get("KTP_FLEET_SSH_PASSWORD") and (
        bool(aliases) or not env.get("KTP_FLEET_SSH_KEY", "").strip())
    # Only ktp-verify-deploy.py issues rcon, and only under --check-runtime. Giving
    # it the value whenever it is the child beats parsing the child's flags here --
    # that coupling breaks the next time the child grows a flag.
    want_rcon = name in NEEDS_RCON and not env.get("KTP_RCON_PASSWORD")
    if not (want_ssh or want_rcon):
        propagate_ssh_aliases(env, aliases)
        return env

    root = project_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import ktp_hosts                      # the single source of truth
    except ImportError as exc:
        raise SystemExit(
            "cannot import ktp_hosts from %s for the fleet credential (%s).\n"
            "Set the credential in the environment instead, or run this from a "
            "checkout that sits inside the project root." % (root, exc))

    if want_ssh:
        try:
            env["KTP_FLEET_SSH_PASSWORD"] = ktp_hosts.FLEET_SSH_PASSWORD
        except AttributeError as exc:
            raise SystemExit("ktp_hosts has no FLEET_SSH_PASSWORD (%s) -- a renamed "
                             "attribute surfaces downstream as AuthenticationException, "
                             "which reads like a host problem." % exc)
    if want_rcon:
        try:
            env["KTP_RCON_PASSWORD"] = ktp_hosts.FLEET_RCON_PASSWORD
        except AttributeError:
            # Said, not raised. The child already exits non-zero naming this
            # credential and saying no host was contacted, and a second gate in
            # front of a working one is a second thing to misfire. Silence is the
            # only wrong answer: it is what made a partial verify look complete.
            print("ktp_hosts has no FLEET_RCON_PASSWORD, so %s cannot be given one "
                  "-- it will refuse a --check-runtime leg rather than skip it"
                  % name, file=sys.stderr)

    propagate_ssh_aliases(env, aliases)
    return env


def unsatisfied_credentials(target: str, env: dict) -> list:
    """Credential-shaped env names the child reads that nothing in env sets.

    Read out of the child's source on purpose. The defect this reports is exactly
    a hand-kept list going stale -- so a hand-kept list is the one thing it must
    not be. A name here is not automatically wrong: a child may read a password it
    does not need because a key is configured instead. It is wrong when the child
    then fails to authenticate, and that is the case this makes legible.

    BLIND SPOT, stated rather than discovered later: this sees LITERAL names only.
    ktp-verify-deploy.py resolves its own credentials through
    os.environ.get(env_var, "") over a table, so its names are computed and this
    returns nothing for it. An empty result therefore means 'no literal gap found',
    never 'every credential is wired' -- and reading it as the latter would be the
    same mistake one level up.
    """
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as fh:
            src = fh.read()
    except OSError:
        return []   # not this script's job to report; the exec below will
    return sorted({n for n in CREDENTIAL_NAME.findall(src) if not env.get(n)})


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--list":
        for n in RUNNABLE:
            print(n)
        return 0

    name = os.path.basename(argv[0])
    if name in NOT_RUNNABLE:
        raise SystemExit("%s is deliberately not in this script's allowlist: %s."
                         % (name, NOT_RUNNABLE[name]))
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
    supplied = ["KTP_FLEET_SSH_KEY" if env.get("KTP_FLEET_SSH_KEY", "").strip()
                else "KTP_FLEET_SSH_PASSWORD"]
    if env.get("KTP_RCON_PASSWORD"):
        supplied.append("KTP_RCON_PASSWORD")
    for alias in SSH_PASSWORD_ALIASES.get(name, ()):
        if env.get(alias):
            supplied.append(alias)
    print("creds:  %s set in child env, value not shown" % ", ".join(supplied))
    for missing in unsatisfied_credentials(target, env):
        why = KNOWN_UNSATISFIED.get(missing)
        if why:
            print("note:   %s reads %s and nothing here sets it -- %s"
                  % (name, missing, why), file=sys.stderr)
        else:
            # Not a refusal: the child may still authenticate another way, and a
            # gate in front of a working one is a second thing to misfire. But an
            # undeclared name is how the GAME_SSH_PASSWORD gap looked, so say so.
            print("note:   %s reads %s, which nothing here sets and nothing has "
                  "accounted for. If it then fails to authenticate, this is why "
                  "-- add it to SSH_PASSWORD_ALIASES or KNOWN_UNSATISFIED."
                  % (name, missing), file=sys.stderr)
    print("-" * 70)
    sys.stdout.flush()
    return subprocess.call([sys.executable, target] + argv[1:], env=env)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
