#!/usr/bin/env python3
"""Diff the running /home/hltvserver/hltv-api.py against scripts/hltv-api.py.example.

The deployed file carries a live shared secret, so it can never be committed; the
`.example` is the only tracked copy and until now nothing compared the two. Every
secret-shaped assignment is replaced with the same placeholder on BOTH sides
before the compare, so the key resolution differing (inline literal on the box,
env var in the example) is not reported as drift and the value cannot reach
stdout.

Redaction is by SHAPE, not by a list of known names: a secret added to the live
file under a new name is redacted the first time it appears. A surviving
secret-shaped assignment with a quoted literal aborts before anything is printed.

Run it on the data server, where the installed copy lives at /usr/local/bin and the
reference does not sit beside it:

    python3 /usr/local/bin/check-hltv-api-drift.py

The reference is searched for rather than assumed, because the only default that
worked was "next to this script" -- true in a checkout, never true once installed,
so the installed copy exited 2 on `cannot read` with no hint about what to pass.

"no drift" is always printed WITH the reference's provenance. The reference is a
checkout on a box that is deliberately never auto-pulled, so agreement with it is
not agreement with `origin/main`, and a silently stale reference is the one way
this check can read clean while the box has genuinely drifted.

Exit: 0 identical, 1 drift, 2 a file is missing or unreadable, 3 redaction failed.
"""
import argparse
import difflib
import os
import re
import subprocess
import sys

DEFAULT_LIVE = "/home/hltvserver/hltv-api.py"
# In order. A checkout has the reference beside this script; the installed copy at
# /usr/local/bin does not, and /opt/ktp-infra is where the data server keeps one.
EXAMPLE_CANDIDATES = (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "hltv-api.py.example"),
    "/opt/ktp-infra/scripts/hltv-api.py.example",
)

PLACEHOLDER = "<redacted-by-drift-check>"

_SECRET_ASSIGN = re.compile(
    r"^(?P<indent>\s*)(?P<name>[A-Za-z_][A-Za-z0-9_]*"
    r"(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD))\s*=\s*(?P<value>.*)$"
)
# A BARE string literal this long is a filled-in credential. An os.environ.get()
# expression is not, even though its env-var name is a quoted string of the same
# shape — that distinction is why this matches the whole value, not a substring.
_BARE_LITERAL = re.compile(r"""^['"][A-Za-z0-9+/=_-]{12,}['"]$""")


def _value(line):
    """The assigned expression with any trailing comment removed."""
    m = _SECRET_ASSIGN.match(line)
    if not m:
        return ""
    v = m.group("value")
    # Only strip a comment that starts outside a string literal.
    depth = None
    for i, ch in enumerate(v):
        if depth is None and ch in "\"'":
            depth = ch
        elif depth is not None and ch == depth:
            depth = None
        elif depth is None and ch == "#":
            v = v[:i]
            break
    return v.strip()


def redact(text):
    """Replace the right-hand side of every secret-shaped assignment."""
    out = []
    for line in text.splitlines():
        m = _SECRET_ASSIGN.match(line)
        if m:
            line = "%s%s = %s" % (m.group("indent"), m.group("name"), PLACEHOLDER)
        out.append(line)
    return out


def leaks(lines):
    """Secret-shaped assignments whose value is a bare credential literal."""
    return [n for n, line in enumerate(lines, 1) if _BARE_LITERAL.match(_value(line))]


def read(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as fh:
        return fh.read()


def resolve_example(explicit):
    """The reference path, or None with the candidates named for the caller."""
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for cand in EXAMPLE_CANDIDATES:
        if os.path.exists(cand):
            return cand
    return None


def _git(cwd, *args):
    return subprocess.run(("git", "-C", cwd) + args, capture_output=True,
                          text=True, timeout=20)


def reference_provenance(path):
    """One line naming the checkout the reference came from.

    UNKNOWN is a real answer and is said out loud. A provenance line that quietly
    disappears leaves "no drift" reading as "matches main", which is the claim this
    checker cannot make: the reference checkout is never auto-pulled.
    """
    d = os.path.dirname(os.path.abspath(path))
    try:
        top = _git(d, "rev-parse", "--show-toplevel")
        if top.returncode:
            return "reference: %s -- provenance UNKNOWN (not a git checkout)" % path
        head = _git(d, "log", "-1", "--format=%h %ci", "HEAD")
        if head.returncode:
            return "reference: %s -- provenance UNKNOWN (no HEAD)" % path
        at = head.stdout.strip()
        behind = _git(d, "rev-list", "--count", "HEAD..origin/main")
        if behind.returncode or not behind.stdout.strip().isdigit():
            return ("reference: %s @ %s -- origin/main not resolvable here, so how "
                    "stale this is cannot be stated" % (path, at))
        n = int(behind.stdout.strip())
        fetched = _git(d, "log", "-1", "--format=%ci", "origin/main")
        ref_date = fetched.stdout.strip() if not fetched.returncode else "unknown"
        if n == 0:
            return ("reference: %s @ %s -- level with this checkout's origin/main "
                    "ref (%s), which is only as fresh as the last fetch"
                    % (path, at, ref_date))
        return ("reference: %s @ %s -- %d commit(s) BEHIND this checkout's own "
                "origin/main ref (%s), which is itself only as fresh as the last "
                "fetch. Agreement with it is not agreement with main."
                % (path, at, n, ref_date))
    except (OSError, subprocess.SubprocessError):
        return "reference: %s -- provenance UNKNOWN (git unavailable)" % path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", default=DEFAULT_LIVE, help="the deployed file (default: %(default)s)")
    ap.add_argument("--example", default=None,
                    help="the tracked copy; searched for when omitted (%s)"
                         % ", ".join(EXAMPLE_CANDIDATES))
    args = ap.parse_args(argv)

    example_path = resolve_example(args.example)
    if example_path is None:
        print("cannot read the reference: %s. Pass --example, or install "
              "hltv-api.py.example at one of: %s"
              % (args.example or "none of the default locations exist",
                 ", ".join(EXAMPLE_CANDIDATES)), file=sys.stderr)
        return 2

    try:
        live_raw, example_raw = read(args.live), read(example_path)
    except OSError as e:
        print("cannot read: %s" % e, file=sys.stderr)
        return 2

    live, example_lines = redact(live_raw), redact(example_raw)

    bad = leaks(live) + leaks(example_lines)
    if bad:
        print("redaction failed on line(s) %s — refusing to print a diff"
              % ", ".join(str(n) for n in bad), file=sys.stderr)
        return 3

    print(reference_provenance(example_path))

    if live == example_lines:
        print("hltv-api: no drift (%d lines, secrets redacted before compare)" % len(live))
        return 0

    diff = difflib.unified_diff(example_lines, live, fromfile=example_path,
                                tofile=args.live, lineterm="")
    print("\n".join(diff))
    added = sum(1 for d in difflib.ndiff(example_lines, live) if d[0] == "+")
    removed = sum(1 for d in difflib.ndiff(example_lines, live) if d[0] == "-")
    print("\nhltv-api: DRIFT — %d line(s) only on the box, %d only in the example"
          % (added, removed))
    return 1


if __name__ == "__main__":
    sys.exit(main())
