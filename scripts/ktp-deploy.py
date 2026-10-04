#!/usr/bin/env python3
"""ktp-deploy -- run stage-wave.py and ktp-wave-ledger.py as a shared, attributed service.

stage-wave.py was written for one operator on one workstation: the ledger is
~/.ktp/waves, the version rows sit next to the workstation checkout, the
credential is in that person's home, and nothing stops a second person staging
at the same moment. Run by several people on the data server, each of those
splits silently -- two ledgers, a row-flip gate that reads nothing, and two
attribution gates that both see a clean fleet and then stack. This wrapper is
the one entry point that holds them together.

On every run it:

  1. takes an exclusive lock, held until the child exits, so the attribution
     gate's check-then-stage cannot interleave with someone else's;
  2. brings the shared checkout to origin/main and proves it (the same
     prepare_tree() the wave sweep uses: fetch, refuse an edited tree, check out
     detached, assert scripts/ matches) -- never a hand-edited copy;
  3. runs the child from that checkout, so the freshness guard inside it checks
     a real tree, with the guard overrides stripped from its environment;
  4. points the child at the SHARED ledger and rows and names the person
     (KTP_DEPLOY_ACTOR), so every wave entry says who staged it;
  5. for `stage`, defaults --pull-live to a shared rollback directory, because the
     fleet keeps no rollback copies and the person staging may not be the person
     who later needs one;
  6. appends one line per run to the audit log: who, which commit, what, exit code.

Usage (on the data server):
  ktp-deploy stage  -f ~/KTPHudObserver.amxx --expect KTPHudObserver.amxx=<md5> \\
                    --base KTPHudObserver.amxx=JimmyLockhart65616/DoD-hud-observer@<sha>
  ktp-deploy stage  --preflight-only
  ktp-deploy ledger status
  ktp-deploy ledger reconcile

Wrapper-only flag (removed before the child sees argv):
  --no-pull-live    stage without preserving the live builds (a first-ever deploy
                    of an artifact has no live copy, and --pull-live is fatal on that)

Env (all optional):
  KTP_DEPLOY_HOME        shared state root (default /var/lib/ktp-deploy):
                         waves/, rollback/, fleet-versions.md, stage.lock, audit.log
  KTP_DEPLOY_TREE        the shared checkout (default /opt/ktp-deploy/KTPInfrastructure)
  KTP_DEPLOY_REMOTE      its clone URL (default the public KTPInfrastructure repo)
  KTP_CLAUDE_MD          version rows (default $KTP_DEPLOY_HOME/fleet-versions.md)
  KTP_WAVE_LEDGER_DIR    wave ledger (default $KTP_DEPLOY_HOME/waves)
  KTP_FLEET_SSH_KEY      per-person dodserver key (default ~/.ssh/ktp_deploy_ed25519 if present)
  KTP_DEPLOY_PASSWORD_FILE  shared-password fallback (default /etc/ktp-deploy/fleet-ssh-password)
  KTP_DEPLOY_ACTOR       honoured only for root, who otherwise has no name to record

Exit codes: the child's, except 2 when this wrapper could not run it at all.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import os
import shlex
import subprocess
import sys

# realpath: installed as a /usr/local/bin symlink into the shared checkout.
HERE = os.path.dirname(os.path.realpath(__file__))
CHILDREN = {"stage": "scripts/stage-wave.py", "ledger": "scripts/ktp-wave-ledger.py"}


def _load_sweep():
    spec = importlib.util.spec_from_file_location("ktp_wave_sweep",
                                                  os.path.join(HERE, "ktp-wave-sweep.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sweep = _load_sweep()
CouldNotLook = sweep.CouldNotLook


class Busy(Exception):
    pass


def deploy_home() -> str:
    return os.environ.get("KTP_DEPLOY_HOME") or "/var/lib/ktp-deploy"


def actor() -> str:
    """The person, never `root` when a person is knowable."""
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    named = os.environ.get("KTP_DEPLOY_ACTOR", "").strip() if is_root else ""
    sudo = os.environ.get("SUDO_USER", "").strip()
    if named:
        return named
    if sudo and sudo != "root":
        return sudo
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return "unknown"


class Lock:
    """An exclusive, non-blocking lock released by the kernel if the holder dies.

    A second deployer is told who holds it rather than queued behind them: waiting
    out someone else's wave and then staging over its result is the stacking the
    attribution gate exists to stop.
    """

    def __init__(self, path: str, who: str):
        self.path, self.who, self.fh = path, who, None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.fh = open(self.path, "a+", encoding="utf-8")
        try:
            try:
                import fcntl
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except ImportError:
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            holder = self._holder()
            self.fh.close()
            raise Busy("another ktp-deploy run holds %s (%s)" % (self.path, holder or "holder unknown"))
        try:
            with open(self.path + ".holder", "w", encoding="utf-8") as h:
                h.write("%s pid %d since %s\n" % (self.who, os.getpid(),
                                                  _dt.datetime.now(_dt.timezone.utc).isoformat()))
        except OSError:
            pass
        return self

    def _holder(self) -> str:
        try:
            with open(self.path + ".holder", encoding="utf-8") as h:
                return h.read().strip()
        except OSError:
            return ""

    def __exit__(self, *exc):
        try:
            os.unlink(self.path + ".holder")
        except OSError:
            pass
        self.fh.close()


def _trust_tree(env: dict, tree: str) -> None:
    """The checkout belongs to whoever created it, and git refuses to run in a
    repository another user owns. safe.directory is honoured from command-scope
    config, which GIT_CONFIG_COUNT is, so this reaches every git the guard runs."""
    n = int(env.get("GIT_CONFIG_COUNT") or 0)
    env["GIT_CONFIG_KEY_%d" % n] = "safe.directory"
    env["GIT_CONFIG_VALUE_%d" % n] = os.path.abspath(tree).replace(os.sep, "/")
    env["GIT_CONFIG_COUNT"] = str(n + 1)


def credential_env(env: dict) -> None:
    """A per-person key if there is one; else the shared password file; else fail here,
    before the lock, rather than half-way through a stage."""
    if env.get("KTP_FLEET_SSH_KEY") or env.get("KTP_FLEET_SSH_PASSWORD"):
        return
    key = os.path.expanduser(os.path.join("~", ".ssh", "ktp_deploy_ed25519"))
    if os.path.isfile(key):
        env["KTP_FLEET_SSH_KEY"] = key
        return
    pw_file = env.get("KTP_DEPLOY_PASSWORD_FILE") or "/etc/ktp-deploy/fleet-ssh-password"
    try:
        with open(pw_file, encoding="utf-8") as fh:
            pw = fh.read().strip()
    except OSError as exc:
        raise CouldNotLook("no fleet credential: no ~/.ssh/ktp_deploy_ed25519, no "
                           "$KTP_FLEET_SSH_KEY / $KTP_FLEET_SSH_PASSWORD, and %s is unreadable "
                           "(%s)" % (pw_file, exc.strerror or exc))
    if not pw:
        raise CouldNotLook("%s is empty" % pw_file)
    env["KTP_FLEET_SSH_PASSWORD"] = pw


def child_argv(cmd: str, args: list[str], tree: str, who: str) -> list[str]:
    argv = [sys.executable, os.path.join(tree, CHILDREN[cmd])]
    if cmd != "stage":
        return argv + args
    rest = [a for a in args if a != "--no-pull-live"]
    reading_only = {"--preflight-only", "--dry-run", "-h", "--help"} & set(rest)
    if "--no-pull-live" in args or "--pull-live" in rest or reading_only:
        return argv + rest
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return argv + ["--pull-live", os.path.join(deploy_home(), "rollback", "%s-%s" % (stamp, who))] + rest


def _audit(home: str, record: dict) -> None:
    try:
        with open(os.path.join(home, "audit.log"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as exc:
        print("warning: could not append to the audit log (%s)" % exc, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in CHILDREN:
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    cmd, args = argv[0], argv[1:]

    os.umask(0o002)
    home = deploy_home()
    tree = os.environ.get("KTP_DEPLOY_TREE") or "/opt/ktp-deploy/KTPInfrastructure"
    remote = os.environ.get("KTP_DEPLOY_REMOTE") or sweep.DEFAULT_REMOTE
    who = actor()
    env = {k: v for k, v in os.environ.items() if k not in sweep.GUARD_OVERRIDES}
    env.setdefault("KTP_CLAUDE_MD", os.path.join(home, "fleet-versions.md"))
    env.setdefault("KTP_WAVE_LEDGER_DIR", os.path.join(home, "waves"))
    env["KTP_DEPLOY_ACTOR"] = who
    _trust_tree(env, tree)

    record = {"at": _dt.datetime.now(_dt.timezone.utc).isoformat(), "actor": who,
              "cmd": cmd, "argv": args, "commit": None, "rc": 2}
    try:
        if not os.path.isfile(env["KTP_CLAUDE_MD"]):
            raise CouldNotLook("version rows not found at %s -- the row-flip gate would read "
                               "nothing" % env["KTP_CLAUDE_MD"])
        credential_env(env)
        with Lock(os.path.join(home, "stage.lock"), who):
            # prepare_tree runs git in-process, so it needs the trust setting too.
            os.environ.update({k: v for k, v in env.items() if k.startswith("GIT_CONFIG_")})
            record["commit"] = sweep.prepare_tree(tree, remote)
            full = child_argv(cmd, args, tree, who)
            print("[ktp-deploy] %s as %s from %s at %s" % (cmd, who, tree, record["commit"][:12]),
                  file=sys.stderr)
            print("[ktp-deploy] %s" % " ".join(shlex.quote(a) for a in full[1:]), file=sys.stderr)
            record["rc"] = subprocess.run(full, cwd=tree, env=env).returncode
    except Busy as exc:
        print("FATAL: %s. Nothing was run." % exc, file=sys.stderr)
        record["refused"] = str(exc)
    except CouldNotLook as exc:
        print("FATAL: could not run -- %s. Nothing was run." % exc, file=sys.stderr)
        record["refused"] = str(exc)
    _audit(home, record)
    return record["rc"]


if __name__ == "__main__":
    raise SystemExit(main())
