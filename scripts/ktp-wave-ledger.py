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

Each artifact also carries its BUILD BASE -- the source commit it was compiled
from -- because the md5 alone answers "is this the same file" and never "has
this moved since". Of eleven artifacts on the fleet only three had a base
recorded anywhere, and the missing eight cannot be recovered: none of these
artifacts is byte-reproducible (`.amxx` bakes a per-minute BUILD_TIME, ReHLDS
bakes a build-id and `__DATE__`), so rebuilding candidate commits and comparing
md5s returns a MISMATCH for the correct base and reads as "none of these built
it". `stats_logging.amxx`'s base is gone for exactly that reason. Stage time is
the only moment the base is known, so that is where it is written.

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
-- it is operator state, and this repo is public. Several people staging means
one shared directory, not one per home: ktp-deploy.py points every deployer at
the same one, and each entry records who staged it (`staged_by`).

Usage:
  ktp-wave-ledger.py status                     # what is pending, and what is due
  ktp-wave-ledger.py check [--no-clear]         # CLAUDE.md only; no fleet, no network -- but it WRITES
  ktp-wave-ledger.py reconcile                  # read the fleet, then gate on CLAUDE.md
  ktp-wave-ledger.py sweep [--no-ledger]        # the same whole-fleet read, marks nothing (timer)
  ktp-wave-ledger.py record -a NAME=MD5:REMOTE_DIR [-a ...] --hosts a,b --targets 24 \
                            --base NAME=owner/repo@sha

"No fleet, no network" is not "no side effect": `check` MARKS a satisfied wave
reconciled in the ledger unless `--no-clear` is passed. `sweep` says it marks
nothing, which makes `check` read the same way -- it does not. Use `--no-clear`
whenever you are reading state rather than closing out a wave.

The unit of reconciliation is the RESTART. The 03:00 swap activates every staged
`.new`, including ones no wave recorded: the 2026-09-08 swap activated
stats_logging and ktp_cvar 7.38 while the ledger held stats_logging alone, and a
2026-09-10 ktp_cvar stage never entered the ledger. So `reconcile` and `sweep`
read every pinned artifact and every staged `.new` on every instance, and a wave
is marked reconciled only when the whole fleet agrees with CLAUDE.md:

  UNLEDGERED_LIVE    live md5 its row does not carry, and no wave staged it
  LIVE_NOT_ON_ROW    live md5 its row does not carry (a wave staged it, or no ledger read)
  ROW_NOT_LIVE       the row's first md5 -- the build it says is live -- is on no instance
  NOT_UNIFORM        instances disagree: a partial activation
  STAGED_UNLEDGERED  a `.new` in no pending wave, which the next swap activates regardless

Exit codes (`check` / `reconcile` / `sweep`):
  0  nothing due, or every due wave's rows agree with the fleet
  1  a row is STALE -- the fleet moved and CLAUDE.md did not -- or a finding above
  2  could not check (CLAUDE.md unreadable, fleet unreachable, no ledger). Never a pass.
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
    "ktp_file.amxx": "KTPFileChecker",
    "KTPAdminAudit.amxx": "KTPAdminAudit",
    "KTPHLTVRecorder.amxx": "KTPHLTVRecorder",
    "KTPHudObserver.amxx": "KTPHudObserver",
    "KTPGrenadeLoadout.amxx": "KTPGrenadeLoadout",
    "KTPGrenadeDamage.amxx": "KTPGrenadeDamage",
    "KTPScoreTracker.amxx": "KTPScoreTracker",
}

# Tried before the component name: the table splits KTPAMXX into one row per artifact.
ROW_ALIASES = {
    "ktpamx_i386.so": ("KTPAMXX core",),
    "dodx_ktp_i386.so": ("KTPAMXX dodx",),
    "stats_logging.amxx": ("stats_logging.amxx",),
}

MD5_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)
MD5_IN_TEXT_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", re.IGNORECASE)

# A build base: `<sha>`, optionally repo-qualified as `owner/repo@<sha>`, with a
# `-dirty` suffix when the tree it was built in was not clean. The repo half is
# not decoration -- a bare short sha is ambiguous across the ~30 repos in this
# estate, and a base nobody can resolve is not a record. A dirty base is worth
# storing verbatim: it says the artifact is NOT that commit, which is a fact the
# next reader needs and cannot get any other way.
BASE_RE = re.compile(r"^(?:[A-Za-z0-9._-]+/[A-Za-z0-9._-]+@)?[0-9a-f]{7,40}(?:-dirty)?$",
                     re.IGNORECASE)

NO_BASE = ("NOT RECORDED -- and not recoverable: this artifact is not byte-reproducible, "
           "so rebuilding candidate commits returns a mismatch for the CORRECT base")


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

# Fleet-writing entry point: refuse to run from a checkout behind origin/main
# (ktp_script_freshness.py). An older copy never SEES the flags it lacks.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ktp_script_freshness import require_current  # noqa: E402


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


def rows_for(text: str, basename: str) -> tuple[str | None, list[str]]:
    """(row name, lines) for the most specific version-table row naming this artifact."""
    component = COMPONENT_BY_BASENAME.get(basename)
    if not component:
        return None, []
    for name in ROW_ALIASES.get(basename, ()) + (component,):
        rows = component_rows(text, name)
        if rows:
            return name, rows
    return component, []


def row_claim(text: str, basename: str) -> str | None:
    """The first md5 after a row's first cell: by the table's convention, the build it says is live."""
    _name, rows = rows_for(text, basename)
    for r in rows:
        m = MD5_IN_TEXT_RE.search(r.strip().strip("|").split("|", 1)[1])
        if m:
            return m.group(0).lower()
    return None


def check_row(text: str, basename: str, md5: str, version: str | None = None) -> RowFinding:
    """Does CLAUDE.md carry `md5` for `basename`'s component?"""
    md5 = md5.lower()
    component, rows = rows_for(text, basename)
    says = f" (should read {version})" if version else ""

    if component:
        if rows:
            if any(md5 in r.lower() for r in rows):
                return RowFinding(basename, md5, component, True, "row",
                                  f"{component} row carries {md5}.")
            elsewhere = " The md5 appears elsewhere in the file but not on that row." \
                if md5 in text.lower() else ""
            return RowFinding(basename, md5, component, False, "row",
                              f"{component} row does NOT carry {md5}{says} -- "
                              f"the row was not flipped after activation.{elsewhere}")
        # A mapped component with no row is a table rename, not a pass -- and it is
        # what every pinned artifact reports when the file being checked is not the
        # one the rows actually live in, so say that before blaming the mapping.
        found = md5 in text.lower()
        return RowFinding(basename, md5, component, found, "no-row",
                          f"no version-table row named `{component}` in this file -- the table was "
                          f"renamed, the mapping in COMPONENT_BY_BASENAME is stale, or the rows moved "
                          f"to a different file (every pinned artifact failing the same way is the "
                          f"tell). Default is .claude/skills/fleet-versions/SKILL.md, one level above "
                          f"this repo; pass --claude-md or set $KTP_CLAUDE_MD to check elsewhere. "
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


def deploy_actor() -> str:
    """Who is running this, for the record. A shared ledger with no name on an
    entry cannot say whose wave is blocking the next stage.

    $KTP_DEPLOY_ACTOR is what ktp-deploy.py sets; SUDO_USER is the person behind
    a `sudo`, which `getuser()` would report as root.
    """
    for v in (os.environ.get("KTP_DEPLOY_ACTOR"), os.environ.get("SUDO_USER")):
        if v and v.strip() and v.strip() != "root":
            return v.strip()
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return "unknown"


def _write_json(path: str, entry: dict) -> str:
    """Write beside `path`, so a reader racing the writer never sees half a file."""
    tmp = f"{path}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entry, fh, indent=2)
        fh.write("\n")
    return tmp


def _publish_new(d: str, stem: str, entry: dict) -> str:
    """Create wave-<id>.json without ever replacing one that exists.

    An exists-then-open check lets two stagers sharing a ledger both pick the
    same id and the second silently overwrites the first. os.link refuses an
    existing target atomically, so the loser moves on to the next suffix.
    """
    n = 1
    while True:
        wave_id = stem if n == 1 else f"{stem}-{n}"
        entry["wave_id"] = wave_id
        path = os.path.join(d, f"wave-{wave_id}.json")
        tmp = _write_json(path, entry)
        try:
            os.link(tmp, path)
            return path
        except FileExistsError:
            n += 1
        finally:
            os.unlink(tmp)


def record_wave(artifacts: list[dict], hosts: list[str], targets: int,
                narrowed: bool = False, staged_at: float | None = None) -> str:
    """Write one wave's intent. `artifacts` items: basename, md5, remote_dir, version?, base?

    `base` is accepted as None so a hand-recorded or pre-existing wave still
    loads, but a base that IS supplied has to be well-formed -- a typo silently
    stored is the same as no record at all, only harder to notice.

    `build_time` is the stamp the staged build baked, and `replaces_build_time`
    the stamps it overwrites. With `base` they are what makes an artifact
    replayable: `.amxx` md5s are not reproducible across minutes, so a build
    whose stamp was not recorded here cannot be rebuilt to its own md5 even from
    the right commit, and the fleet keeps no rollback copies.
    """
    staged_at = time.time() if staged_at is None else staged_at
    for a in artifacts:
        if not MD5_RE.match(a.get("md5", "")):
            raise ValueError(f"{a.get('basename')}: not an md5: {a.get('md5')!r}")
        if a.get("base") is not None and not BASE_RE.match(str(a["base"])):
            raise ValueError(f"{a.get('basename')}: not a build base: {a['base']!r} "
                             "(want [owner/repo@]<7-40 hex>[-dirty])")
    d = ledger_dir()
    os.makedirs(d, exist_ok=True)
    # Second-resolution ids collide, and a collision would silently overwrite an
    # unreconciled wave -- the one file that must not go missing.
    stem = datetime.fromtimestamp(staged_at, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    entry = {
        "wave_id": stem,
        "staged_at": int(staged_at),
        "staged_by": deploy_actor(),
        "activates_after": next_activation(staged_at),
        "hosts": sorted(hosts),
        "targets": targets,
        "narrowed": narrowed,
        "artifacts": [{"basename": a["basename"], "md5": a["md5"].lower(),
                       "remote_dir": a.get("remote_dir", ""), "version": a.get("version"),
                       "base": a.get("base"),
                       "build_time": a.get("build_time"),
                       "replaces_build_time": a.get("replaces_build_time")}
                      for a in artifacts],
        "reconciled_at": None,
        "reconciled_by": None,
    }
    return _publish_new(d, stem, entry)


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
    entry["reconciled_actor"] = deploy_actor()
    os.replace(_write_json(path, entry), path)


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

def default_claude_md() -> str:
    """Where the version-table rows live: the fleet-versions skill, one level
    above this repo -- the rows moved out of the root CLAUDE.md itself, which
    now only points at the skill. $KTP_CLAUDE_MD overrides this for a
    different copy (a worktree, a rehearsal file); it does not have to be
    named CLAUDE.md."""
    env = os.environ.get("KTP_CLAUDE_MD")
    if env:
        return os.path.expanduser(env)
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(
        here, "..", "..", ".claude", "skills", "fleet-versions", "SKILL.md"))


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
            f"Row-flip gate: {len(due)} activated wave(s) to check, but the version-row file could "
            f"not be read at {claude_md or default_claude_md()}.",
            "Set $KTP_CLAUDE_MD (or pass --claude-md) to the file that carries the rows -- default is "
            ".claude/skills/fleet-versions/SKILL.md, one level above this repo. An unverifiable gate "
            "is not a passed gate.",
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
                   f"on {entry['targets']} instance(s), staged by {entry.get('staged_by') or 'NOT RECORDED'}")
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
#
# The swap activates every `.new` it finds, whoever staged it, so the read covers
# the whole fleet rather than the artifacts one wave happened to name.

SWAP_DIRS = (
    "serverfiles",
    "serverfiles/dod/addons/ktpamx/dlls",
    "serverfiles/dod/addons/ktpamx/modules",
    "serverfiles/dod/addons/ktpamx/plugins",
)

_DONE = "__KTP_SWEEP_DONE__"


@dataclass
class FleetRead:
    live: dict[str, dict[str, str | None]] = field(default_factory=dict)   # basename -> {inst: md5|None}
    staged: dict[str, dict[str, str]] = field(default_factory=dict)        # basename -> {inst: md5 of .new}
    errors: dict[str, str] = field(default_factory=dict)                   # host or inst -> why unread


def _load_d2f():
    import importlib.util

    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("deploy_to_fleet",
                                                  os.path.join(here, "deploy-to-fleet.py"))
    d2f = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("deploy_to_fleet", d2f)
    spec.loader.exec_module(d2f)
    return d2f


def sweep_basenames(waves: list[tuple[str, dict]]) -> dict[str, str]:
    """{basename: remote_dir} -- every mapped artifact, plus anything a wave ever staged."""
    route = {"engine_i486.so": "serverfiles", "ktpamx_i386.so": SWAP_DIRS[1]}
    out = {}
    for b in COMPONENT_BY_BASENAME:
        out[b] = route.get(b) or (SWAP_DIRS[2] if b.endswith(".so") else SWAP_DIRS[3])
    for _p, e in waves:
        for a in e.get("artifacts", []):
            if a.get("remote_dir"):
                out.setdefault(a["basename"], a["remote_dir"])
    return out


def host_command(ports: list[int], basenames: dict[str, str], user: str = "dodserver") -> str:
    """One shell line per host: md5 every pinned file and every staged .new, per instance."""
    files = " ".join(f"{d}/{b}" for b, d in sorted(basenames.items()))
    news = " ".join(f"{d}/*.new" for d in SWAP_DIRS)
    parts = []
    for p in ports:
        parts.append(f"echo '@@ {p}'; ( cd /home/{user}/dod-{p} 2>/dev/null || {{ echo '@@NODIR'; exit 0; }}; "
                     f"nice -n 19 md5sum {files} 2>/dev/null; nice -n 19 md5sum {news} 2>/dev/null; true )")
    parts.append(f"echo {_DONE}")
    return "; ".join(parts)


def parse_host_output(hk: str, ports: list[int], text: str, basenames: dict[str, str],
                      read: FleetRead) -> None:
    """Fold one host's output into `read`. A section that read nothing is an error, never 'all absent'."""
    if _DONE not in text:
        read.errors[hk] = "output truncated (no completion marker) -- not treated as absent"
        return
    sections: dict[int, list[str]] = {}
    cur = None
    for ln in text.splitlines():
        ln = ln.strip()
        if ln.startswith("@@ "):
            try:
                cur = int(ln[3:])
            except ValueError:
                cur = None
            if cur is not None:
                sections[cur] = []
        elif cur is not None and ln and ln != _DONE:
            sections[cur].append(ln)
    for p in ports:
        inst = f"{hk}:{p}"
        lines = sections.get(p)
        if lines is None:
            read.errors[inst] = "no output section"
            continue
        if "@@NODIR" in lines:
            read.errors[inst] = f"instance directory dod-{p} missing"
            continue
        got_live = False
        seen: dict[str, str] = {}
        for ln in lines:
            parts = ln.split(None, 1)
            if len(parts) != 2 or not MD5_RE.match(parts[0]):
                continue
            base = os.path.basename(parts[1].strip())
            if base.endswith(".new"):
                read.staged.setdefault(base[:-4], {})[inst] = parts[0].lower()
            else:
                seen[base] = parts[0].lower()
                got_live = True
        if not got_live:
            read.errors[inst] = "md5sum returned nothing -- not treated as absent"
            continue
        for b in basenames:
            read.live.setdefault(b, {})[inst] = seen.get(b)


def fleet_read(basenames: dict[str, str], hosts: list[str] | None = None) -> FleetRead:
    """Read every pinned artifact and staged .new on every active instance. md5sum only."""
    import paramiko

    d2f = _load_d2f()
    read = FleetRead()
    for hk in hosts or list(d2f.SERVERS):
        info = d2f.SERVERS[hk]
        ports = list(info.get("ports", d2f.PORTS))
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(info["host"], username=info["user"], timeout=30,
                        **d2f.fleet_ssh_auth())
            _, so, _ = ssh.exec_command(host_command(ports, basenames, info["user"]), timeout=120)
            parse_host_output(hk, ports, so.read().decode(errors="replace"), basenames, read)
        except Exception as ex:
            read.errors[hk] = f"{type(ex).__name__}: {ex}"
        finally:
            ssh.close()
    return read


# --------------------------------------------------------------------------
# The restart reconcile: the whole fleet against CLAUDE.md and the ledger
# --------------------------------------------------------------------------

@dataclass
class SweepFinding:
    kind: str          # UNLEDGERED_LIVE | LIVE_NOT_ON_ROW | ROW_NOT_LIVE | NOT_UNIFORM | STAGED_UNLEDGERED
    basename: str
    md5: str | None
    instances: list[str]
    detail: str


def _short(insts: list[str], total: int) -> str:
    return f"{len(insts)}/{total}" + (f" ({', '.join(sorted(insts))})" if len(insts) <= 4 else "")


def sweep(read: FleetRead, text: str, waves: list[tuple[str, dict]] | None) -> list[SweepFinding]:
    """Everything the fleet runs or has staged that CLAUDE.md or the ledger cannot account for.

    `waves` is every recorded wave, reconciled or not; None means no ledger was read,
    and then provenance is reported as unknown rather than as absent.
    """
    ledgered = set()
    pending = set()
    for _p, e in waves or []:
        for a in e.get("artifacts", []):
            ledgered.add((a["basename"], a["md5"].lower()))
            if not e.get("reconciled_at"):
                pending.add((a["basename"], a["md5"].lower()))

    out: list[SweepFinding] = []
    for base in sorted(read.live):
        seen = read.live[base]
        by_md5: dict[str, list[str]] = {}
        for inst, md5 in seen.items():
            by_md5.setdefault(md5 or "ABSENT", []).append(inst)
        present = {m: i for m, i in by_md5.items() if m != "ABSENT"}
        if not present and base not in COMPONENT_BY_BASENAME:
            continue
        total = len(seen)

        if present and len(by_md5) > 1:
            spread = "; ".join(f"{m} on {_short(i, total)}" for m, i in sorted(by_md5.items()))
            out.append(SweepFinding("NOT_UNIFORM", base, None, sorted(seen), f"partial activation: {spread}"))

        for md5, insts in sorted(present.items()):
            f = check_row(text, base, md5)
            if f.ok:
                continue
            if waves is None:
                kind, why = "LIVE_NOT_ON_ROW", "ledger not read, so provenance unknown"
            elif (base, md5) in ledgered:
                kind, why = "LIVE_NOT_ON_ROW", "a recorded wave staged it; flip the row"
            else:
                kind, why = "UNLEDGERED_LIVE", "no wave in the ledger staged it -- it reached the fleet outside stage-wave.py"
            out.append(SweepFinding(kind, base, md5, insts,
                                    f"live on {_short(insts, total)}; {f.detail} ({why})"))

        claim = row_claim(text, base)
        if claim and claim not in present:
            out.append(SweepFinding("ROW_NOT_LIVE", base, claim, [],
                                    f"the row's live md5 {claim} is on no instance "
                                    f"(fleet: {', '.join(sorted(by_md5)) or 'nothing read'})"))

    if waves is not None:
        for base in sorted(read.staged):
            by_md5 = {}
            for inst, md5 in read.staged[base].items():
                by_md5.setdefault(md5, []).append(inst)
            for md5, insts in sorted(by_md5.items()):
                if (base, md5) not in pending:
                    out.append(SweepFinding("STAGED_UNLEDGERED", base, md5, insts,
                                            f"{base}.new staged on {len(insts)} instance(s) and in no pending "
                                            "wave -- the next 03:00 swap activates it with nothing to reconcile"))
    return out


def format_sweep(read: FleetRead, findings: list[SweepFinding], ledger_note: str) -> list[str]:
    insts = {i for seen in read.live.values() for i in seen}
    staged = sum(len(v) for v in read.staged.values())
    lines = [f"Fleet: {len(insts)} instance(s) read, {len(read.live)} pinned artifact(s), "
             f"{staged} staged .new file(s). Ledger: {ledger_note}."]
    for f in findings:
        lines.append(f"  {f.kind}: {f.basename}" + (f" {f.md5}" if f.md5 else "") + f" -- {f.detail}")
    if not findings:
        lines.append("  clean: every live pinned md5 is on its CLAUDE.md row, and every staged .new is in a pending wave.")
    return lines


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
              f"  staged by {e.get('staged_by') or 'NOT RECORDED'}"
              f"{'  NARROWED (not a fleet wave)' if e.get('narrowed') else ''}")
        for a in e["artifacts"]:
            v = f"  {a['version']}" if a.get("version") else ""
            print(f"    {a['basename']}  {a['md5']}{v}")
            print(f"      built from {a['base']}" if a.get("base")
                  else f"      built from {NO_BASE}")
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


def _print_read_errors(read: FleetRead) -> None:
    print("FATAL: could not read the whole fleet:", file=sys.stderr)
    for k, v in sorted(read.errors.items()):
        print(f"  {k}: {v}", file=sys.stderr)
    print("Aborting -- an unverifiable gate is not a passed gate.", file=sys.stderr)


def _cmd_reconcile(args) -> int:
    now = time.time()
    waves = [(p, e) for p, e in load_waves() if e["activates_after"] <= now]
    if not waves and args.no_fleet:
        print("Nothing to reconcile: no activated wave is awaiting a row flip. "
              "(--no-fleet: the fleet was NOT swept, so a stage that skipped the ledger is invisible here.)")
        return 0

    got = read_claude_md(args.claude_md)
    if got is None:
        print(f"FATAL: cannot read CLAUDE.md at {args.claude_md or default_claude_md()} -- "
              "set $KTP_CLAUDE_MD. Not a pass.", file=sys.stderr)
        return 2
    path, text = got

    read: FleetRead | None = None
    if not args.no_fleet:
        read = fleet_read(sweep_basenames(load_waves(include_reconciled=True)))
        if read.errors:
            _print_read_errors(read)
            print("(--no-fleet checks CLAUDE.md alone, and says so.)", file=sys.stderr)
            return 2
    if not waves:
        print("No activated wave is awaiting a row flip -- sweeping the fleet anyway, because a "
              "stage that skipped the ledger leaves no wave behind.")

    rc = 0
    ready = []
    for p, entry in waves:
        print(f"\nwave {entry['wave_id']} ({entry['targets']} instance(s)):")
        live: dict[str, dict[str, str | None]] = {}
        if read is not None:
            hosts = set(entry["hosts"])
            live = {a["basename"]: {i: m for i, m in read.live.get(a["basename"], {}).items()
                                    if i.split(":", 1)[0] in hosts}
                    for a in entry["artifacts"]}

        stale, unactivated = [], []
        for a in entry["artifacts"]:
            want = a["md5"]
            if read is not None:
                seen = live[a["basename"]]
                matched = [k for k, v in seen.items() if v == want]
                if not seen or len(matched) != len(seen):
                    others = sorted({v or "ABSENT" for v in seen.values()} - {want})
                    print(f"  {a['basename']}: NOT activated -- {len(matched)}/{len(seen)} on {want}"
                          f" (also: {', '.join(others)})")
                    unactivated.append(a["basename"])
                    continue
                print(f"  {a['basename']}: live {len(matched)}/{len(seen)} on {want}")
            else:
                print(f"  {a['basename']}: {want} (fleet NOT read -- --no-fleet)")
            # Quoted here because reconcile is where the CLAUDE.md row gets
            # written, and the row is the only place the base outlives the
            # ledger entry that is about to be marked reconciled.
            print(f"    built from {a['base']}" if a.get("base") else f"    built from {NO_BASE}")
            f = check_row(text, a["basename"], want, a.get("version"))
            print(f"    CLAUDE.md: {'OK' if f.ok else 'STALE'} -- {f.detail}")
            if not f.ok:
                stale.append(f)

        if stale:
            rc = 1
        elif unactivated:
            print(f"  left open: {', '.join(unactivated)} has not activated on every target yet.")
        else:
            ready.append((p, entry))

    blocking: list[SweepFinding] = []
    if read is not None:
        findings = sweep(read, text, load_waves(include_reconciled=True))
        print("\nrestart (the whole fleet, not only the waves above):")
        for ln in format_sweep(read, findings, "read"):
            print(f"  {ln}")
        if findings:
            rc = 1
        blocking = [f for f in findings if f.kind != "STAGED_UNLEDGERED"]

    for p, entry in ready:
        if blocking:
            print(f"  left open: wave {entry['wave_id']} -- the restart moved more than the ledger "
                  "accounts for, so it is not reconciled until the whole fleet agrees.")
        else:
            mark_reconciled(p, entry, "reconcile" if read is not None else "reconcile --no-fleet")
            print(f"  wave {entry['wave_id']} reconciled.")

    if rc:
        print(f"\nFAILED: CLAUDE.md ({path}) disagrees with what the fleet is running.",
              file=sys.stderr)
        print("The fleet md5 is the truth. Flip the row, then re-run.", file=sys.stderr)
    return rc


def _cmd_sweep(args) -> int:
    got = read_claude_md(args.claude_md)
    if got is None:
        print(f"FATAL: cannot read CLAUDE.md at {args.claude_md or default_claude_md()} -- "
              "set $KTP_CLAUDE_MD. Not a pass.", file=sys.stderr)
        return 2
    _path, text = got

    if args.no_ledger:
        waves, note = None, "NOT read (--no-ledger), so provenance and staged .new are unchecked"
    elif not os.path.isdir(ledger_dir()):
        print(f"FATAL: no wave ledger at {ledger_dir()} -- set $KTP_WAVE_LEDGER_DIR, or pass "
              "--no-ledger to sweep against CLAUDE.md alone.", file=sys.stderr)
        return 2
    else:
        waves = load_waves(include_reconciled=True)
        note = f"{len(waves)} wave(s) at {ledger_dir()}"

    read = fleet_read(sweep_basenames(waves or []))
    if read.errors:
        _print_read_errors(read)
        return 2
    findings = sweep(read, text, waves)
    for ln in format_sweep(read, findings, note):
        print(ln)
    return 1 if findings else 0


def _cmd_record(args) -> int:
    bases = {}
    for spec in args.base:
        name, sep, base = spec.partition("=")
        if not sep or not BASE_RE.match(base.strip()):
            sys.exit(f"FATAL: --base wants NAME=[owner/repo@]<7-40 hex>[-dirty], got {spec!r}")
        bases[name.strip()] = base.strip()

    artifacts = []
    for spec in args.artifact:
        name, _, rest = spec.partition("=")
        md5, _, remote_dir = rest.partition(":")
        if not MD5_RE.match(md5):
            sys.exit(f"FATAL: -a wants NAME=MD5[:REMOTE_DIR], got {spec!r}")
        artifacts.append({"basename": name, "md5": md5, "remote_dir": remote_dir,
                          "base": bases.pop(name, None)})
    # A --base naming an artifact that is not in the wave is a typo in the one
    # field nobody can reconstruct later, so it is fatal rather than ignored.
    if bases:
        sys.exit(f"FATAL: --base names artifacts not in this wave: {', '.join(sorted(bases))}")

    path = record_wave(artifacts, args.hosts.split(","), args.targets)
    print(path)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--claude-md",
                    help="File carrying the version-table rows (default: $KTP_CLAUDE_MD, else "
                         "../../.claude/skills/fleet-versions/SKILL.md -- the rows moved out of the "
                         "root CLAUDE.md; this flag/env var name is unchanged)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="List recorded waves.")
    s.add_argument("--all", action="store_true", help="Include reconciled waves.")
    s.set_defaults(func=_cmd_status)

    c = sub.add_parser("check", help="Gate on CLAUDE.md alone. No network -- but it marks a "
                                     "satisfied wave reconciled; --no-clear to only report.")
    c.add_argument("--no-clear", action="store_true",
                   help="Report without marking a satisfied wave reconciled.")
    c.set_defaults(func=_cmd_check)

    r = sub.add_parser("reconcile", help="Read the fleet, then gate on CLAUDE.md.")
    r.add_argument("--no-fleet", action="store_true",
                   help="Skip the fleet read and check CLAUDE.md against the recorded md5 only. "
                        "Weaker, and the output says so.")
    r.set_defaults(func=_cmd_reconcile)

    sw = sub.add_parser("sweep", help="Read-only restart reconcile for a timer: the whole fleet "
                                      "against CLAUDE.md and the ledger. Marks nothing.")
    sw.add_argument("--no-ledger", action="store_true",
                    help="Sweep against CLAUDE.md alone where no ledger exists. Provenance and staged "
                         ".new are then unchecked, and the output says so.")
    sw.set_defaults(func=_cmd_sweep)

    w = sub.add_parser("record", help="Record a wave by hand (stage-wave.py does this for you).")
    w.add_argument("-a", "--artifact", action="append", required=True, metavar="NAME=MD5[:REMOTE_DIR]")
    w.add_argument("--base", action="append", default=[], metavar="NAME=BASE",
                   help="Source commit NAME was built from, e.g. "
                        "KTPMatchHandler.amxx=afraznein/KTPMatchHandler@b891b0e. Repeatable. "
                        "stage-wave.py supplies this for you and refuses to stage without it.")
    w.add_argument("--hosts", required=True)
    w.add_argument("--targets", type=int, required=True)
    w.set_defaults(func=_cmd_record)

    args = ap.parse_args(argv)
    require_current(__file__, also=["deploy-to-fleet.py"],
                    purpose="write the ledger the fleet is reconciled against")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
