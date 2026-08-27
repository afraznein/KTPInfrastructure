#!/usr/bin/env python3
"""Read-only drift check for the two restart scripts in every game host's ~.

WHY THIS EXISTS. `~/restart-all-servers.sh` sat untouched on the fleet from
February 2026 while the generator in provision/install-linuxgsm.sh was fixed
twice, and it drifted into two mutually incompatible variants that fail in
different ways -- one dies at the first healthy server, the other dies on an
instance directory that was deleted in July. Nothing reported either, because
nothing was looking. `ktp-scheduled-restart.sh` drifted the other way: the
tracked .example moved ahead of the fleet, and the gitignored local copy fell
three weeks behind both.

Read-only. It reads four files per host and writes nothing anywhere.
It does not restart, stop, or touch a game server.

Usage:
    python3 ktp-restart-drift.py [--verbose]

Host addressing and credentials come from the same JSON the fleet audit uses:
/etc/ktp/audit-fleet.json, or KTP_AUDIT_FLEET_CONFIG. See
scripts/audit-fleet.json.example for the schema. Nothing is hardcoded here.

Exit: 0 = every reached host matches on every check AND every host was reached
      1 = drift found, or a host could not be reached

A host that could not be reached is a FAILURE, not a skip. A sweep that
silently drops a connection renders as a clean fleet, which is the failure mode
this script is meant to close rather than reproduce.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import paramiko
except ImportError:
    sys.exit("ERROR: paramiko not installed (pip3 install paramiko)")

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "scripts" / "ktp-scheduled-restart.sh.example"
POST_SWAP = REPO / "scripts" / "ktp-verify-post-swap.sh"
INSTALLER = REPO / "provision" / "install-linuxgsm.sh"

REMOTE_SCHEDULED = "~/ktp-scheduled-restart.sh"
REMOTE_MANUAL = "~/restart-all-servers.sh"
REMOTE_POST_SWAP = "~/ktp-verify-post-swap.sh"

# Lines whose VALUE is a secret or a deployment-specific id. Compared by
# assignment target only -- the value never leaves the host and never reaches
# this process's output, and a rotated secret does not read as drift.
SECRET_ASSIGNMENTS = ("AUTH_SECRET", "CHANNEL_KTP", "CHANNEL_EXTERNAL",
                      "RELAY_URL", "EDIT_URL")
_SECRET_RE = re.compile(r"^\s*(%s)\s*=" % "|".join(SECRET_ASSIGNMENTS))


def mask_secrets(text: str) -> list[str]:
    """Replace the value half of every secret-carrying assignment."""
    out = []
    for line in text.splitlines():
        m = _SECRET_RE.match(line)
        out.append("%s=<masked>" % m.group(1) if m else line)
    return out


def strip_comments(text: str) -> str:
    """Drop comment bodies before asserting a property.

    install-linuxgsm.sh's own warning comment names `((running++))` as the thing
    the code deliberately is not, so a check that greps the raw file reports the
    correct generator as buggy. Not a perfect shell lexer -- a `#` inside a
    string is stripped too -- which is acceptable because every check below asks
    whether a construct is ABSENT, and over-stripping can only lose evidence of
    a construct, never invent one.
    """
    return "\n".join(re.sub(r"#.*", "", line) for line in text.splitlines())


# Properties the manual restart script must satisfy, asserted against the
# comment-stripped body. Each is (label, predicate, why-it-matters).
MANUAL_PROPERTIES = [
    ("no `set -e`",
     lambda s: not re.search(r"^\s*set\s+-[a-z]*e", s, re.M),
     "under `set -e` the verify loop dies at the first healthy server"),
    ("no bare `((var++))`",
     lambda s: not re.search(r"\(\(\s*[A-Za-z_]\w*\+\+\s*\)\)"
                             r"|\(\(\s*\+\+[A-Za-z_]\w*\s*\)\)", s),
     "post-increment from 0 evaluates to 0 and returns exit status 1"),
    ("instance list derived at run time",
     lambda s: "dod-*" in s,
     "an install-time count outlives the install (Chicago's deleted 27019)"),
    ("no hardcoded port literals",
     lambda s: not re.search(r"2701[5-9]\s+2701[5-9]|for\s+i\s+in\s+1\s+2\s+3", s),
     "the same root cause, spelled the other way"),
    ("verify compares against the discovered count",
     lambda s: "KTP_PORTS[@]" in s,
     "a literal /5 misreports on any host that is not five instances"),
]


def generated_manual_region() -> str:
    """The slice of install-linuxgsm.sh that emits ~/restart-all-servers.sh.

    Starts at create_management_scripts() so the emitted discovery function is
    included, ends at the chmod that closes the heredoc.
    """
    text = INSTALLER.read_text(encoding="utf-8")
    start = text.find("create_management_scripts() {")
    end = text.find('chmod +x "$HOME/restart-all-servers.sh"')
    if start < 0 or end < 0:
        sys.exit("ERROR: cannot locate the restart-all-servers.sh generator in "
                 "%s -- the installer was restructured; update this script "
                 "rather than deleting the check." % INSTALLER)
    return text[start:end]


def load_hosts():
    path = Path(os.environ.get("KTP_AUDIT_FLEET_CONFIG", "/etc/ktp/audit-fleet.json"))
    if not path.exists():
        sys.exit("ERROR: fleet config not found at %s\n"
                 "Copy scripts/audit-fleet.json.example there, or set "
                 "KTP_AUDIT_FLEET_CONFIG." % path)
    hosts = json.loads(path.read_text()).get("hosts")
    if not isinstance(hosts, list) or not hosts:
        sys.exit('ERROR: %s has no non-empty "hosts" array' % path)
    return hosts


def connect(entry):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    auth = {}
    if entry.get("key_filename"):
        auth["key_filename"] = entry["key_filename"]
    elif entry.get("password"):
        auth["password"] = entry["password"]
    client.connect(entry["host"], username=entry.get("user", "dodserver"),
                   timeout=45, banner_timeout=45, auth_timeout=45,
                   allow_agent=False, look_for_keys=False, **auth)
    return client


def fetch(client, remote_path):
    """Return the file's text, or None if it is not there.

    `cat` is used rather than SFTP so `~` is expanded by the remote shell.
    stdout and the exit status are read separately: a non-zero status is the
    only reliable "absent" signal, since an empty stdout is also what a
    zero-byte file looks like.
    """
    _, out, _ = client.exec_command("cat %s" % remote_path, timeout=60)
    data = out.read().decode("utf-8", "replace")
    return data if out.channel.recv_exit_status() == 0 else None


def check_host(name, client, verbose):
    """Return a list of problem strings; empty means this host is clean."""
    problems = []

    sched = fetch(client, REMOTE_SCHEDULED)
    if sched is None:
        problems.append("%s is ABSENT" % REMOTE_SCHEDULED)
    else:
        want = mask_secrets(EXAMPLE.read_text(encoding="utf-8"))
        got = mask_secrets(sched)
        # The .example carries a provenance header the deployed copy does not;
        # compare the executable body, which starts at the first non-comment line.
        def body(lines):
            for i, line in enumerate(lines):
                if line.strip() and not line.lstrip().startswith("#"):
                    return lines[i:]
            return lines
        if body(want) != body(got):
            problems.append(
                "%s DIVERGES from scripts/ktp-scheduled-restart.sh.example "
                "(compared with secret values masked)" % REMOTE_SCHEDULED)
        for placeholder in ("YOUR_AUTH_SECRET_HERE", "YOUR_KTP_CHANNEL_ID",
                            "YOUR_EXTERNAL_CHANNEL_ID"):
            if placeholder in sched:
                problems.append(
                    "%s still holds the %s placeholder -- the 03:00 Discord "
                    "notification is silently dead on this host"
                    % (REMOTE_SCHEDULED, placeholder))

    manual = fetch(client, REMOTE_MANUAL)
    if manual is None:
        problems.append("%s is ABSENT" % REMOTE_MANUAL)
    else:
        stripped = strip_comments(manual)
        for label, predicate, why in MANUAL_PROPERTIES:
            if not predicate(stripped):
                problems.append("%s fails property '%s' -- %s"
                                % (REMOTE_MANUAL, label, why))

    swap = fetch(client, REMOTE_POST_SWAP)
    if swap is None:
        problems.append("%s is ABSENT (added by #164)" % REMOTE_POST_SWAP)
    elif swap.splitlines() != POST_SWAP.read_text(encoding="utf-8").splitlines():
        problems.append("%s DIVERGES from scripts/ktp-verify-post-swap.sh"
                        % REMOTE_POST_SWAP)

    if verbose and not problems:
        print("  %s: all checks pass" % name)
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    for required in (EXAMPLE, POST_SWAP, INSTALLER):
        if not required.exists():
            sys.exit("ERROR: %s missing -- run this from a KTPInfrastructure "
                     "checkout" % required)

    # The generator is the reference for the manual script's properties, so hold
    # it to them too. Catches a regression in the repo before it can be pushed
    # to a host and read as fleet drift. Scoped to the region that EMITS the
    # script: the installer's own `set -e` on line 25 is correct for the
    # installer and would otherwise fail the generated script's property.
    gen = strip_comments(generated_manual_region())
    gen_fail = [label for label, predicate, _ in MANUAL_PROPERTIES
                if not predicate(gen)]
    if gen_fail:
        print("REPO: provision/install-linuxgsm.sh fails: %s" % ", ".join(gen_fail))

    hosts = load_hosts()
    reached, unreachable, dirty = [], [], {}
    for entry in hosts:
        name = entry.get("name", entry["host"])
        try:
            client = connect(entry)
        except Exception as ex:
            unreachable.append((name, type(ex).__name__, str(ex)[:120]))
            continue
        reached.append(name)
        try:
            problems = check_host(name, client, args.verbose)
        finally:
            client.close()
        if problems:
            dirty[name] = problems

    print()
    for name, problems in dirty.items():
        print("%s:" % name)
        for p in problems:
            print("  DRIFT: %s" % p)
    for name, kind, detail in unreachable:
        print("%s: UNREACHABLE (%s) %s" % (name, kind, detail))

    print("\nhosts reached: %d/%d  clean: %d  drifted: %d"
          % (len(reached), len(hosts), len(reached) - len(dirty), len(dirty)))
    return 1 if (dirty or unreachable or gen_fail) else 0


if __name__ == "__main__":
    sys.exit(main())
