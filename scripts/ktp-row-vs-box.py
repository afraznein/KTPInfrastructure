#!/usr/bin/env python3
"""ktp-row-vs-box -- does each data-server version row still name the build on the box?

The fleet-versions table records the live hash of every data-server daemon, and
nothing re-reads it. ktp-wave-ledger.py reconciles fleet WAVES against the game
instances; a daemon swapped by hand on the data server reaches no ledger, so a
row can sit a deploy or two behind with every check green. This reads each row's
claim and hashes the file on the box.

  python scripts/ktp-row-vs-box.py ROWS.md --host root@<data-server>
  python scripts/ktp-row-vs-box.py ROWS.md --host root@<data-server> \\
      --component KTPHLStatsX --path 'KTPProfileAggregator=/opt/.../aggregator.py'

READ-ONLY. One SSH session; the only remote commands are md5sum/sha256sum on the
row's paths and on a path that must not exist. No credential is held or read:
authentication is the caller's SSH key or agent.

WHAT A ROW MUST SAY TO BE CHECKED
  The first 32- or 64-hex token after the component cell is the live identity
  (the table's convention, shared with ktp-wave-ledger.py). The file it describes
  is the backticked absolute path that directly follows it, as in
      **`<md5>`** · 297,242 B on `/opt/hlstatsx/scripts/hlstats.pl`
  A row with no such path, or whose path is a /proc/<pid> link that does not
  survive a restart, is UNPARSEABLE rather than guessed at. --path supplies one.

Per row:
  OK           the box's hash equals the row's live hash
  ROW_STALE    it does not: the box moved and the row did not, or the reverse
  UNPARSEABLE  the row carries no checkable hash + path
  UNREADABLE   the box could not hash the path
  ROW_MISSING  a requested component has no row in the file

Exit: 0 every row OK - 1 at least one ROW_STALE - 2 the check could not trust
itself (unreadable file, SSH failure, a failed control), or a row it could not
check (missing, unparseable, unreadable). A failed control outranks a stale row:
it means no verdict on this run can be relied on.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shlex
import sys
from dataclasses import dataclass

# Rows that describe a file on the data server. A name that stops matching a row
# is reported as ROW_MISSING, never skipped: a renamed row is not a checked row.
DATA_SERVER_COMPONENTS = (
    "KTPHLStatsX",
    "KTPProfileAggregator",
    "KTPFileDistributor",
    "HLTV `proxy.so`",
    "KTPAntiCheat (API)",
)

HASH_RE = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{64}|[0-9a-fA-F]{32})(?![0-9a-fA-F])")
# The path must be the hash's own: bold/backtick closers, an optional size, an
# optional "— measured", then `on `/path``. Anything looser lets a later clause's
# path (a backup, a rollback pin) stand in for the live file.
PATH_AFTER_HASH_RE = re.compile(
    r"^[`*]*(?:\s*·\s*[\d,]+\s*B)?\s*(?:—\s*measured\s+)?on\s+`(/[^`\s]+)`")
PROC_PID_RE = re.compile(r"^/proc/\d+/")
CONTROL_PATH = "/nonexistent/ktp-row-vs-box-control"


def _load_ledger():
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "ktp_wave_ledger", os.path.join(here, "ktp-wave-ledger.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ktp_wave_ledger", mod)
    spec.loader.exec_module(mod)
    return mod


_ledger = _load_ledger()


@dataclass
class Row:
    component: str
    status: str = ""
    expected: str | None = None
    path: str | None = None
    actual: str | None = None
    detail: str = ""

    @property
    def algo(self) -> str:
        return "sha256" if self.expected and len(self.expected) == 64 else "md5"


def parse_row(text: str, component: str, path_override: str | None = None) -> Row:
    row = Row(component)
    lines = _ledger.component_rows(text, component)
    if not lines:
        row.status, row.detail = "ROW_MISSING", "no version-table row has this first cell"
        return row
    if len(lines) > 1:
        row.status, row.detail = "UNPARSEABLE", f"{len(lines)} rows share this first cell"
        return row
    rest = lines[0].strip().strip("|").split("|", 1)[1]
    m = HASH_RE.search(rest)
    if not m:
        row.status, row.detail = "UNPARSEABLE", "no md5 or sha256 on the row"
        return row
    row.expected = m.group(1).lower()
    if path_override:
        row.path = path_override
        return row
    p = PATH_AFTER_HASH_RE.match(rest[m.end():])
    if not p:
        row.status, row.detail = "UNPARSEABLE", "the live hash is not followed by `on `/path``"
        return row
    if PROC_PID_RE.match(p.group(1)):
        row.status = "UNPARSEABLE"
        row.detail = f"{p.group(1)} names a process id, which does not survive a restart"
        return row
    row.path = p.group(1)
    return row


def judge(row: Row, actual: str | None) -> str:
    if actual is None:
        return "UNREADABLE"
    return "OK" if actual == row.expected else "ROW_STALE"


def remote_command(rows: list[Row]) -> str:
    """One line per path: `<tag> <hash-or-ERR>`. The control goes first."""
    parts = []
    for i, r in enumerate([Row("control", expected="0" * 32, path=CONTROL_PATH)] + rows):
        tool = "sha256sum" if r.algo == "sha256" else "md5sum"
        parts.append(f"h=$({tool} -- {shlex.quote(r.path)} 2>/dev/null) "
                     f"&& echo \"{i} ${{h%% *}}\" || echo \"{i} ERR\"")
    return "; ".join(parts)


def parse_remote(out: str, n: int) -> dict[int, str | None] | None:
    got: dict[int, str | None] = {}
    for line in out.splitlines():
        bits = line.split()
        if len(bits) != 2 or not bits[0].isdigit():
            continue
        idx, val = int(bits[0]), bits[1]
        got[idx] = None if val == "ERR" else val.lower()
    if set(got) != set(range(n + 1)):
        return None
    return got


def run_ssh(target: str, command: str, key: str | None, timeout: int = 60) -> str:
    import paramiko

    user, _, host = target.rpartition("@")
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(host, username=user or None, key_filename=key, timeout=30,
                    allow_agent=True, look_for_keys=True)
        _, so, _ = ssh.exec_command(command, timeout=timeout)
        return so.read().decode(errors="replace")
    finally:
        ssh.close()


def check(text: str, components, overrides: dict[str, str], fetch) -> tuple[list[Row], list[str]]:
    """Rows judged, plus reasons the run cannot be trusted. `fetch(cmd) -> stdout`."""
    rows = [parse_row(text, c, overrides.get(c)) for c in components]
    distrust = [f"--path names {c!r}, which is not a component being checked"
                for c in overrides if c not in components]
    live = [r for r in rows if not r.status]
    if not live:
        distrust.append("no row carried a checkable hash and path")
        return rows, distrust
    try:
        out = fetch(remote_command(live))
    except Exception as ex:  # noqa: BLE001 -- any failure here is "could not look"
        distrust.append(f"SSH failed: {type(ex).__name__}: {ex}")
        for r in live:
            r.status, r.detail = "UNREADABLE", "no SSH session"
        return rows, distrust
    got = parse_remote(out, len(live))
    if got is None:
        distrust.append("the box's reply did not account for every path")
        for r in live:
            r.status, r.detail = "UNREADABLE", "reply incomplete"
        return rows, distrust
    if got[0] is not None:
        distrust.append(f"control failed: hashing {CONTROL_PATH} returned {got[0]}, "
                        "so a failed read cannot be told from a successful one")
    for i, r in enumerate(live, 1):
        r.actual = got[i]
        r.status = judge(r, r.actual)
        if r.status == "OK" and not wrong_hash_is_caught(text, r, overrides.get(r.component)):
            distrust.append(f"control failed: {r.component}'s row with one digit of its "
                            f"{r.algo} changed still read as OK")
    return rows, distrust


def wrong_hash_is_caught(text: str, row: Row, path_override: str | None) -> bool:
    """Re-read the row with its live hash altered by one digit, against the same box hash.

    End to end through the parser, so it fails if the claim ever stops coming
    from the row -- not merely if string comparison breaks.
    """
    wrong = ("0" if row.expected[0] != "0" else "1") + row.expected[1:]
    mutated = []
    for line in text.splitlines():
        if line in _ledger.component_rows(line, row.component):
            line = re.sub(re.escape(row.expected), wrong, line, count=1, flags=re.I)
        mutated.append(line)
    again = parse_row("\n".join(mutated), row.component, path_override)
    return again.expected == wrong and judge(again, row.actual) == "ROW_STALE"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rows_file", help="Markdown carrying the version table (e.g. the "
                                      "fleet-versions SKILL.md, which is not in this repo)")
    ap.add_argument("--host", required=True, help="user@host of the data server")
    ap.add_argument("--key", help="SSH private key; default is the agent and ~/.ssh")
    ap.add_argument("--component", action="append", default=[],
                    help="Check only this row. Repeatable. Default: every data-server row.")
    ap.add_argument("--path", action="append", default=[], metavar="COMPONENT=PATH",
                    help="Hash PATH for COMPONENT instead of the path on its row.")
    args = ap.parse_args(argv)

    try:
        with open(args.rows_file, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as ex:
        print(f"FATAL: cannot read {args.rows_file}: {ex}", file=sys.stderr)
        return 2
    if not any(_ledger._row_first_cell(line) for line in text.splitlines()):
        print(f"FATAL: {args.rows_file} has no markdown table rows -- wrong file?", file=sys.stderr)
        return 2

    overrides = {}
    for spec in args.path:
        name, sep, path = spec.partition("=")
        if not sep or not path.startswith("/"):
            print(f"FATAL: --path wants COMPONENT=/absolute/path, got {spec!r}", file=sys.stderr)
            return 2
        overrides[name] = path

    components = tuple(args.component) or DATA_SERVER_COMPONENTS
    rows, distrust = check(text, components, overrides,
                           lambda cmd: run_ssh(args.host, cmd, args.key))

    for r in rows:
        where = f" {r.path}" if r.path else ""
        if r.status == "OK":
            print(f"OK           {r.component}:{where} {r.algo} {r.expected}")
        elif r.status == "ROW_STALE":
            print(f"ROW_STALE    {r.component}:{where} row says {r.expected}, box has {r.actual}")
        elif r.status == "UNREADABLE":
            print(f"UNREADABLE   {r.component}:{where} {r.detail or 'the box could not hash it'}")
        else:
            print(f"{r.status:<12} {r.component}: {r.detail}")
    for d in distrust:
        print(f"UNTRUSTED    {d}", file=sys.stderr)

    if distrust:
        return 2
    if any(r.status == "ROW_STALE" for r in rows):
        return 1
    return 0 if all(r.status == "OK" for r in rows) else 2


if __name__ == "__main__":
    sys.exit(main())
