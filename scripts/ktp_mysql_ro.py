#!/usr/bin/env python3
"""Run a read against the data server's MySQL as `ktp_ro`, a login that can only SELECT.

    python scripts/ktp_mysql_ro.py query.sql
    python scripts/ktp_mysql_ro.py --prove-only

WHY A LOGIN AND NOT A SESSION FLAG
----------------------------------
`SET SESSION TRANSACTION READ ONLY` does refuse writes on MySQL 8.0, root included,
but it is a request the SQL makes of itself: the same session can undo it with
`START TRANSACTION READ WRITE` or `SET SESSION transaction_read_only=0`, and a path
that never sends it is simply read-write. A login with only SELECT refuses with
ERROR 1142 whatever the session says. See docs/runbooks/MYSQL_READ_ONLY_READS.md.

WHAT IS PROVED BEFORE THE QUERY IS SENT
---------------------------------------
On every run, over the same SSH connection, the helper asks the server who it is and
what it may do, and requires all three answers to be PRESENT:

  * CURRENT_USER() is exactly ktp_ro@localhost,
  * every SHOW GRANTS line grants nothing beyond USAGE / SELECT / SHOW VIEW,
  * a statement the server cannot run comes back as ERROR 1193, so an empty answer
    from a broken transport cannot pass as a clean one.

Any answer missing or different is exit 2 and the query is never sent.

ktp_ro authenticates with auth_socket, so there is no password anywhere: the helper
SSHes in as the data server's admin user (credentials from ktp_hosts.py at the
project root) and runs `runuser -u ktp_ro -- mysql`.

Exit codes: 0 = query ran. 1 = query ran and MySQL reported an error. 2 = the
read-only proof failed or the host could not be reached; nothing was queried.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Callable, Optional, Tuple

RO_USER = "ktp_ro"
DB = "hlstatsx"
ALLOWED_PRIVS = {"USAGE", "SELECT", "SHOW VIEW"}
DISCRIMINATOR = "ktp_ro_no_such_variable"

PROOF_SQL = (
    "SELECT CONCAT('IDENTITY=', CURRENT_USER()); SHOW GRANTS; "
    f"SELECT @@session.{DISCRIMINATOR}"
)
PROOF_CMD = (
    f"runuser -u {RO_USER} -- mysql --batch --skip-column-names "
    f"-e \"{PROOF_SQL}\" 2>&1"
)
QUERY_CMD = f"runuser -u {RO_USER} -- mysql --batch {DB}"

_GRANT = re.compile(
    r"^GRANT (?P<privs>.+?) ON (?P<obj>\S+) TO `" + RO_USER + r"`@`localhost`$")

# exec(command, stdin_text) -> (stdout, stderr, exit status)
Exec = Callable[[str, Optional[str]], Tuple[str, str, int]]


def proof_problems(text: str) -> list[str]:
    """Every reason the proof output does NOT show a SELECT-only ktp_ro session."""
    problems: list[str] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    identity = [ln for ln in lines if ln.startswith("IDENTITY=")]
    if identity != [f"IDENTITY={RO_USER}@localhost"]:
        problems.append(f"identity is {identity or '<absent>'}, not {RO_USER}@localhost")

    grants = [ln for ln in lines if ln.startswith("GRANT ")]
    if not grants:
        problems.append("no GRANT line came back")
    saw_select = False
    for ln in grants:
        m = _GRANT.match(ln)
        if not m:
            problems.append(f"grant not of the SELECT-only shape: {ln}")
            continue
        privs = {p.strip() for p in m.group("privs").split(",")}
        extra = privs - ALLOWED_PRIVS
        if extra:
            problems.append(f"grant carries {sorted(extra)}: {ln}")
        saw_select = saw_select or "SELECT" in privs
    if grants and not saw_select:
        problems.append("no SELECT grant, so a read would fail for the wrong reason")

    if not any(ln.startswith("ERROR 1193") and DISCRIMINATOR in ln for ln in lines):
        problems.append("the harness did not report an error for a statement the "
                        "server cannot run, so a silent answer proves nothing")

    unexpected = [ln for ln in lines
                  if not (ln.startswith("IDENTITY=") or ln.startswith("GRANT ")
                          or (ln.startswith("ERROR 1193") and DISCRIMINATOR in ln))]
    if unexpected:
        problems.append(f"unexpected output: {unexpected[:3]}")
    return problems


def run(sql: Optional[str], exec_: Exec, max_ms: int = 10000) -> int:
    out, err, _ = exec_(PROOF_CMD, None)
    problems = proof_problems(out + "\n" + err)
    if problems:
        print("REFUSED: read-only proof failed; nothing was queried.", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    print(f"read-only proof ok: {RO_USER}@localhost, SELECT-only, harness reports errors",
          file=sys.stderr)
    if sql is None:
        return 0
    out, err, rc = exec_(QUERY_CMD, f"SET SESSION max_execution_time={int(max_ms)};\n{sql}")
    sys.stdout.write(out)
    if err:
        sys.stderr.write(err)
    return 0 if rc == 0 else 1


def _ssh_exec_factory() -> Exec:
    sys.path.insert(0, os.environ.get("KTP_PROJECT_ROOT", r"N:/Nein_/KTP Git Projects"))
    import ktp_hosts  # noqa: E402

    client = ktp_hosts.connect("data")

    def exec_(command: str, stdin_text: Optional[str]) -> Tuple[str, str, int]:
        i, o, e = client.exec_command(command, timeout=180)
        if stdin_text is not None:
            i.write(stdin_text)
        i.channel.shutdown_write()
        out = o.read().decode("utf-8", "replace")
        err = e.read().decode("utf-8", "replace")
        return out, err, o.channel.recv_exit_status()

    return exec_


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sql_file", nargs="?", help="file holding the SQL to run")
    ap.add_argument("--prove-only", action="store_true",
                    help="run the read-only proof and stop")
    ap.add_argument("--max-ms", type=int, default=10000,
                    help="max_execution_time for the session (default 10000)")
    args = ap.parse_args(argv)
    if bool(args.sql_file) == args.prove_only:
        ap.error("give exactly one of sql_file or --prove-only")
    sql = None
    if args.sql_file:
        with open(args.sql_file, encoding="utf-8") as fh:
            sql = fh.read()
        if not sql.strip():
            ap.error(f"{args.sql_file} is empty")
    try:
        exec_ = _ssh_exec_factory()
    except Exception as exc:  # unreachable host must not read as an empty result
        print(f"REFUSED: could not reach the data server: {exc}", file=sys.stderr)
        return 2
    return run(sql, exec_, args.max_ms)


if __name__ == "__main__":
    sys.exit(main())
