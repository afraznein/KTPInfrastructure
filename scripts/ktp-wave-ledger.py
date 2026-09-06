#!/usr/bin/env python3
"""ktp-wave-ledger -- turn the post-activation version-row flip into a gate.

The bump checklist puts the root `CLAUDE.md` row flip AFTER the 03:00 ET swap,
so it depends on someone coming back the next morning, and nothing fails when
they do not. On 2026-09-01 one wave left TWO rows stale at once -- KTPCvarChecker
said 7.36 while the fleet ran 7.37, KTPMatchHandler said 0.10.168 while the
fleet ran 0.10.170 -- and only an md5 sweep a day later found it. Both artifacts
were fine. Only the record was wrong, while the table read as authoritative.

That is a process defect, not two mistakes, so the remedy is not a louder
reminder. The intent is recorded at STAGE time, when the md5 is already known
(`stage-wave.py --expect NAME=MD5`), and two things consume it:

  * `reconcile` re-reads the fleet and FAILS if CLAUDE.md does not carry the
    md5 the fleet is actually running.
  * `stage-wave.py` refuses to stage the NEXT wave while an earlier one has
    activated and its rows still disagree. That is the half that does not rely
    on memory: the gate sits on the action the operator is going to take
    anyway, and flipping the row is what clears it.

Three things this deliberately does NOT do:

  * It does not parse a version out of an artifact. `.amxx` files embed no
    version string, and the module `.so`s self-report hardcoded literals that
    have rotted before. The md5 is the identity, so the md5 is what is matched.
  * It does not require the OLD md5 to be gone from the row. Rows legitimately
    name prior builds and `_fleet-backups/` paths; "the new hash is present" is
    the assertion that holds.
  * It never writes to the fleet and never restarts anything. Its fleet read is
    `md5sum` and nothing else.

The ledger lives OUTSIDE this repo ($KTP_WAVE_LEDGER_DIR, default ~/.ktp/waves)
-- it is operator state, and this repo is public.

Usage:
  ktp-wave-ledger.py status                     # what is pending, and what is due
  ktp-wave-ledger.py check                      # CLAUDE.md only; no fleet, no network
  ktp-wave-ledger.py reconcile                  # read the fleet, then gate on CLAUDE.md
  ktp-wave-ledger.py record -a NAME=MD5:REMOTE_DIR [-a ...] --hosts a,b --targets 24

Exit codes (`check` / `reconcile`):
  0  nothing due, or every due wave's rows agree with the fleet
  1  a row is STALE -- the fleet moved and CLAUDE.md did not
  2  could not check (CLAUDE.md unreadable, fleet unreachable). Never a pass.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

DEFAULT_LEDGER_DIR = os.path.join("~", ".ktp", "waves")

# The nightly swap. `.new` files activate here and nowhere else -- extension
# mode never reloads plugins on a map change.
ACTIVATION_HOUR_ET = 3

# Artifact basename -> the component name in CLAUDE.md's version table, used
# only to NARROW the search to that component's row. An unmapped basename falls
# back to a file-wide md5 search and SAYS SO; it never passes by default.
COMPONENT_BY_BASENAME = {
    "engine_i486.so": "KTP-ReHLDS",
    "ktpamx_i386.so": "KTPAMXX",
    "dodx_ktp_i386.so": "KTPAMXX",
    "stats_logging.amxx": "KTPAMXX",
    "reapi_ktp_i386.so": "KTP-ReAPI",
    "amxxcurl_ktp_i386.so": "KTPAMXXCurl",
    "KTPMatchHandler.amxx": "KTPMatchHandler",
    "KTPPracticeMode.amxx": "KTPPracticeMode",
    "ktp_cvar.amxx": "KTPCvarChecker",
    "KTPFileChecker.amxx": "KTPFileChecker",
    "KTPAdminAudit.amxx": "KTPAdminAudit",
    "KTPHLTVRecorder.amxx": "KTPHLTVRecorder",
    "KTPHudObserver.amxx": "KTPHudObserver",
    "KTPGrenadeLoadout.amxx": "KTPGrenadeLoadout",
    "KTPGrenadeDamage.amxx": "KTPGrenadeDamage",
    "KTPScoreTracker.amxx": "KTPScoreTracker",
}

MD5_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)


# --------------------------------------------------------------------------
# When does a staged wave become live
# --------------------------------------------------------------------------

def _nth_sunday(year: int, month: int, n: int) -> int:
    """Day-of-month of the nth Sunday."""
    d = date(year, month, 1)
    first = 1 + (6 - d.weekday()) % 7
    return first + 7 * (n - 1)


def _et_offset_hours(dt_utc: datetime) -> int:
    """Hours ET is behind UTC. Post-2007 US rule; only reached where the tz
    database is absent, and a wrong hour shifts when the gate arms, not what
    it decides."""
    y = dt_utc.year
    edt_start = datetime(y, 3, _nth_sunday(y, 3, 2), 7, 0, tzinfo=timezone.utc)
    edt_end = datetime(y, 11, _nth_sunday(y, 11, 1), 6, 0, tzinfo=timezone.utc)
    return 4 if edt_start <= dt_utc < edt_end else 5


try:
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
except Exception:  # no tzdata (common on Windows without the tzdata package)
    _ET = None


def next_activation(staged_at: float) -> int:
    """Epoch of the first 03:00 ET nightly swap strictly after staged_at."""
    dt = datetime.fromtimestamp(staged_at, tz=timezone.utc)
    for day in range(3):
        if _ET is not None:
            local = dt.astimezone(_ET) + timedelta(days=day)
            cand = local.replace(hour=ACTIVATION_HOUR_ET, minute=0, second=0, microsecond=0)
            epoch = int(cand.timestamp())
        else:
            off = _et_offset_hours(dt)
            local = dt - timedelta(hours=off) + timedelta(days=day)
            cand = local.replace(hour=ACTIVATION_HOUR_ET, minute=0, second=0, microsecond=0)
            epoch = int((cand + timedelta(hours=off)).replace(tzinfo=timezone.utc).timestamp())
        if epoch > staged_at:
            return epoch
    raise RuntimeError("no activation time found within 3 days")


# --------------------------------------------------------------------------
# CLAUDE.md row assertions
# --------------------------------------------------------------------------

@dataclass
class RowFinding:
    basename: str
    md5: str
    component: str | None
    ok: bool
    scope: str          # "row" | "file" | "no-row"
    detail: str


def _row_first_cell(line: str) -> str | None:
    if not line.lstrip().startswith("|"):
        return None
    cells = line.strip().strip("|").split("|")
    return cells[0] if len(cells) >= 2 else None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def component_rows(text: str, component: str) -> list[str]:
    """Version-table lines whose first cell names this component."""
    want = _norm(component)
    out = []
    for line in text.splitlines():
        cell = _row_first_cell(line)
        if cell is not None and _norm(cell) == want:
            out.append(line)
    return out


def check_row(text: str, basename: str, md5: str, version: str | None = None) -> RowFinding:
    """Does CLAUDE.md carry `md5` for `basename`'s component?"""
    md5 = md5.lower()
    component = COMPONENT_BY_BASENAME.get(basename)
    says = f" (should read {version})" if version else ""

    if component:
        rows = component_rows(text, component)
        if rows:
            if any(md5 in r.lower() for r in rows):
                return RowFinding(basename, md5, component, True, "row",
                                  f"{component} row carries {md5}.")
            elsewhere = " The md5 appears elsewhere in the file but not on that row." \
                if md5 in text.lower() else ""
            return RowFinding(basename, md5, component, False, "row",
                              f"{component} row does NOT carry {md5}{says} -- "
                              f"the row was not flipped after activation.{elsewhere}")
        # A mapped component with no row is a table rename, not a pass.
        found = md5 in text.lower()
        return RowFinding(basename, md5, component, found, "no-row",
                          f"no version-table row named `{component}` -- the table was renamed or the "
                          f"mapping in COMPONENT_BY_BASENAME is stale. "
                          f"{'md5 is present somewhere in the file' if found else 'md5 is ABSENT from the file'}.")

    found = md5 in text.lower()
    return RowFinding(basename, md5, None, found, "file",
                      f"`{basename}` maps to no component -- WEAK check, file-wide only. "
                      f"{'md5 present' if found else 'md5 ABSENT from CLAUDE.md'}{says}.")


# --------------------------------------------------------------------------
# Ledger storage
# --------------------------------------------------------------------------

def ledger_dir() -> str:
    return os.path.expanduser(os.environ.get("KTP_WAVE_LEDGER_DIR") or DEFAULT_LEDGER_DIR)


def record_wave(artifacts: list[dict], hosts: list[str], targets: int,
                narrowed: bool = False, staged_at: float | None = None) -> str:
    """Write one wave's intent. `artifacts` items: basename, md5, remote_dir, version?"""
    staged_at = time.time() if staged_at is None else staged_at
    for a in artifacts:
        if not MD5_RE.match(a.get("md5", "")):
            raise ValueError(f"{a.get('basename')}: not an md5: {a.get('md5')!r}")
    d = ledger_dir()
    os.makedirs(d, exist_ok=True)
    # Second-resolution ids collide, and a collision would silently overwrite an
    # unreconciled wave -- the one file that must not go missing.
    stem = datetime.fromtimestamp(staged_at, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    wave_id, n = stem, 1
    while os.path.exists(os.path.join(d, f"wave-{wave_id}.json")):
        n += 1
        wave_id = f"{stem}-{n}"

    entry = {
        "wave_id": wave_id,
        "staged_at": int(staged_at),
        "activates_after": next_activation(staged_at),
        "hosts": sorted(hosts),
        "targets": targets,
        "narrowed": narrowed,
        "artifacts": [{"basename": a["basename"], "md5": a["md5"].lower(),
                       "remote_dir": a.get("remote_dir", ""), "version": a.get("version")}
                      for a in artifacts],
        "reconciled_at": None,
        "reconciled_by": None,
    }
    path = os.path.join(d, f"wave-{wave_id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(entry, fh, indent=2)
        fh.write("\n")
    return path


def load_waves(include_reconciled: bool = False) -> list[tuple[str, dict]]:
    d = ledger_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if not (name.startswith("wave-") and name.endswith(".json")):
            continue
        p = os.path.join(d, name)
        try:
            with open(p, encoding="utf-8") as fh:
                entry = json.load(fh)
        except Exception:
            continue
        if entry.get("reconciled_at") and not include_reconciled:
            continue
        out.append((p, entry))
    out.sort(key=lambda pe: pe[1].get("staged_at", 0))
    return out


def mark_reconciled(path: str, entry: dict, by: str) -> None:
    entry["reconciled_at"] = int(time.time())
    entry["reconciled_by"] = by
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(entry, fh, indent=2)
        fh.write("\n")


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

def default_claude_md() -> str:
    """Root CLAUDE.md -- the version table lives one level above this repo."""
    env = os.environ.get("KTP_CLAUDE_MD")
    if env:
        return os.path.expanduser(env)
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", "CLAUDE.md"))


def read_claude_md(path: str | None = None) -> tuple[str, str] | None:
    """(path, text), or None if it cannot be read. Never returns '' for missing:
    an empty string would satisfy nothing and read as 'every row is stale',
    which is a different verdict from 'I could not look'."""
    p = path or default_claude_md()
    try:
        with open(p, encoding="utf-8") as fh:
            return p, fh.read()
    except OSError:
        return None


@dataclass
class GateResult:
    status: str                      # "clear" | "blocked" | "inconclusive"
    lines: list[str] = field(default_factory=list)
    blocked: list[tuple[dict, list[RowFinding]]] = field(default_factory=list)


def gate(claude_md: str | None = None, now: float | None = None,
         auto_clear: bool = True) -> GateResult:
    """Waves that have already activated but whose CLAUDE.md rows still disagree.

    A wave whose rows now agree is marked reconciled here, so doing the row flip
    is itself what clears the gate -- there is no second command to remember.
    """
    now = time.time() if now is None else now
    waves = load_waves()
    due = [(p, e) for p, e in waves if e.get("activates_after", 0) <= now]
    if not due:
        pending = len(waves)
        note = (f"{pending} wave(s) staged but not yet activated." if pending
                else "no wave awaiting a CLAUDE.md row flip.")
        return GateResult("clear", [f"Row-flip gate: {note}"])

    got = read_claude_md(claude_md)
    if got is None:
        return GateResult("inconclusive", [
            f"Row-flip gate: {len(due)} activated wave(s) to check, but CLAUDE.md could not be read "
            f"at {claude_md or default_claude_md()}.",
            "Set $KTP_CLAUDE_MD to the root CLAUDE.md. An unverifiable gate is not a passed gate.",
        ])

    path, text = got
    lines, blocked = [], []
    for p, entry in due:
        findings = [check_row(text, a["basename"], a["md5"], a.get("version"))
                    for a in entry["artifacts"]]
        bad = [f for f in findings if not f.ok]
        if bad:
            blocked.append((entry, bad))
        elif auto_clear:
            mark_reconciled(p, entry, "stage-gate")
            lines.append(f"Row-flip gate: wave {entry['wave_id']} reconciled "
                         f"({', '.join(a['basename'] for a in entry['artifacts'])}).")
    if blocked:
        return GateResult("blocked", lines, blocked)
    return GateResult("clear", lines or [f"Row-flip gate: clear against {path}."])


def format_block(result: GateResult, claude_md: str | None = None) -> list[str]:
    out = ["FATAL: a previous wave has ACTIVATED and its CLAUDE.md version row is still stale.",
           ""]
    for entry, bad in result.blocked:
        when = datetime.fromtimestamp(entry["activates_after"], tz=timezone.utc)
        out.append(f"  wave {entry['wave_id']} -- activated at {when:%Y-%m-%d %H:%M} UTC "
                   f"on {entry['targets']} instance(s)")
        for f in bad:
            out.append(f"    {f.basename}: {f.detail}")
    out += [
        "",
        f"The fleet moved and the record did not. Flip the row in {claude_md or default_claude_md()}",
        "with the md5 above (the fleet md5 is the truth, not the row's prior claim), then re-run --",
        "the gate clears itself once the row agrees.",
        "",
        "If that wave did NOT activate cleanly, do not flip the row: find the leftover `.new` first",
        "(`ktp-verify-post-swap.sh`). --allow-unreconciled overrides, for a deliberate stack only.",
    ]
    return out


# --------------------------------------------------------------------------
# Fleet read (the strong check) -- md5sum only, never a write
# --------------------------------------------------------------------------

def fleet_md5s(entry: dict) -> dict[str, dict[str, str | None]]:
    """{basename: {"host:port": md5-or-None}} for this wave's target instances."""
    import importlib.util

    import paramiko

    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("deploy_to_fleet",
                                                  os.path.join(here, "deploy-to-fleet.py"))
    d2f = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d2f)

    out: dict[str, dict[str, str | None]] = {a["basename"]: {} for a in entry["artifacts"]}
    for hk in entry["hosts"]:
        info = d2f.SERVERS[hk]
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(info["host"], username=info["user"],
                    password=d2f._fleet_ssh_password(), timeout=30)
        try:
            for port in d2f.SERVERS[hk].get("ports", d2f.PORTS):
                paths = {a["basename"]: f"/home/{info['user']}/dod-{port}/{a['remote_dir']}/{a['basename']}"
                         for a in entry["artifacts"]}
                cmd = "md5sum " + " ".join(f"'{p}'" for p in paths.values()) + " 2>/dev/null"
                _, so, _ = ssh.exec_command(cmd, timeout=60)
                seen = {}
                for ln in so.read().decode().splitlines():
                    parts = ln.split()
                    if len(parts) == 2:
                        seen[os.path.basename(parts[1])] = parts[0].lower()
                for base in paths:
                    out[base][f"{hk}:{port}"] = seen.get(base)
        finally:
            ssh.close()
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _cmd_status(args) -> int:
    waves = load_waves(include_reconciled=args.all)
    if not waves:
        print("No waves recorded." if args.all else "No unreconciled waves.")
        return 0
    now = time.time()
    for _p, e in waves:
        due = "ACTIVATED" if e["activates_after"] <= now else "pending activation"
        if e.get("reconciled_at"):
            due = f"reconciled by {e['reconciled_by']}"
        print(f"{e['wave_id']}  [{due}]  {e['targets']} instance(s)"
              f"{'  NARROWED (not a fleet wave)' if e.get('narrowed') else ''}")
        for a in e["artifacts"]:
            v = f"  {a['version']}" if a.get("version") else ""
            print(f"    {a['basename']}  {a['md5']}{v}")
    return 0


def _cmd_check(args) -> int:
    res = gate(args.claude_md, auto_clear=not args.no_clear)
    if res.status == "inconclusive":
        for ln in res.lines:
            print(ln, file=sys.stderr)
        return 2
    for ln in res.lines:
        print(ln)
    if res.status == "blocked":
        for ln in format_block(res, args.claude_md):
            print(ln, file=sys.stderr)
        return 1
    return 0


def _cmd_reconcile(args) -> int:
    now = time.time()
    waves = [(p, e) for p, e in load_waves() if e["activates_after"] <= now]
    if not waves:
        print("Nothing to reconcile: no activated wave is awaiting a row flip.")
        return 0

    got = read_claude_md(args.claude_md)
    if got is None:
        print(f"FATAL: cannot read CLAUDE.md at {args.claude_md or default_claude_md()} -- "
              "set $KTP_CLAUDE_MD. Not a pass.", file=sys.stderr)
        return 2
    path, text = got

    rc = 0
    for p, entry in waves:
        print(f"\nwave {entry['wave_id']} ({entry['targets']} instance(s)):")
        live: dict[str, dict[str, str | None]] = {}
        if not args.no_fleet:
            try:
                live = fleet_md5s(entry)
            except Exception as ex:
                print(f"  FATAL: could not read the fleet: {ex!r}", file=sys.stderr)
                print("  Aborting -- an unverifiable gate is not a passed gate. "
                      "(--no-fleet checks CLAUDE.md alone, and says so.)", file=sys.stderr)
                return 2

        stale, unactivated = [], []
        for a in entry["artifacts"]:
            want = a["md5"]
            if live:
                seen = live[a["basename"]]
                matched = [k for k, v in seen.items() if v == want]
                if len(matched) != len(seen):
                    others = sorted({v or "ABSENT" for v in seen.values()} - {want})
                    print(f"  {a['basename']}: NOT activated -- {len(matched)}/{len(seen)} on {want}"
                          f" (also: {', '.join(others)})")
                    unactivated.append(a["basename"])
                    continue
                print(f"  {a['basename']}: live {len(matched)}/{len(seen)} on {want}")
            else:
                print(f"  {a['basename']}: {want} (fleet NOT read -- --no-fleet)")
            f = check_row(text, a["basename"], want, a.get("version"))
            print(f"    CLAUDE.md: {'OK' if f.ok else 'STALE'} -- {f.detail}")
            if not f.ok:
                stale.append(f)

        if stale:
            rc = 1
        elif unactivated:
            print(f"  left open: {', '.join(unactivated)} has not activated on every target yet.")
        else:
            mark_reconciled(p, entry, "reconcile" if live else "reconcile --no-fleet")
            print("  reconciled.")

    if rc:
        print(f"\nFAILED: CLAUDE.md ({path}) disagrees with what the fleet is running.",
              file=sys.stderr)
        print("The fleet md5 is the truth. Flip the row, then re-run.", file=sys.stderr)
    return rc


def _cmd_record(args) -> int:
    artifacts = []
    for spec in args.artifact:
        name, _, rest = spec.partition("=")
        md5, _, remote_dir = rest.partition(":")
        if not MD5_RE.match(md5):
            sys.exit(f"FATAL: -a wants NAME=MD5[:REMOTE_DIR], got {spec!r}")
        artifacts.append({"basename": name, "md5": md5, "remote_dir": remote_dir})
    path = record_wave(artifacts, args.hosts.split(","), args.targets)
    print(path)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--claude-md", help="Root CLAUDE.md (default: $KTP_CLAUDE_MD, else ../../CLAUDE.md)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="List recorded waves.")
    s.add_argument("--all", action="store_true", help="Include reconciled waves.")
    s.set_defaults(func=_cmd_status)

    c = sub.add_parser("check", help="Gate on CLAUDE.md alone. No network.")
    c.add_argument("--no-clear", action="store_true",
                   help="Report without marking a satisfied wave reconciled.")
    c.set_defaults(func=_cmd_check)

    r = sub.add_parser("reconcile", help="Read the fleet, then gate on CLAUDE.md.")
    r.add_argument("--no-fleet", action="store_true",
                   help="Skip the fleet read and check CLAUDE.md against the recorded md5 only. "
                        "Weaker, and the output says so.")
    r.set_defaults(func=_cmd_reconcile)

    w = sub.add_parser("record", help="Record a wave by hand (stage-wave.py does this for you).")
    w.add_argument("-a", "--artifact", action="append", required=True, metavar="NAME=MD5[:REMOTE_DIR]")
    w.add_argument("--hosts", required=True)
    w.add_argument("--targets", type=int, required=True)
    w.set_defaults(func=_cmd_record)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
