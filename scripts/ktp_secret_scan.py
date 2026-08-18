#!/usr/bin/env python3
"""Value-based secret scanner for the KTP repos.

Matches literal credential VALUES, not keyword patterns. The distinction is the
whole point: hltv-api.py was called clean twice by keyword greps before a value
check found AUTH_KEY on line 34, and GitHub push protection -- enabled on
KTPInfrastructure -- let a 10-character root password reach a public branch
because it only recognises registered provider formats.

THE CONTRACT. A clean result must carry proof it could have been dirty, so
`clean` is never inferred from "found nothing". Exit 0 requires all of:
  - the canary was found in every file format the walker claims to read
  - the inventory loaded and holds at least one live value
  - the scan scope enumerated to something non-empty
Any of those failing is exit 2, which is deliberately not exit 0: a probe that
cannot fire must never read as a passing gate.

Exit codes:
  0  clean, all self-checks passed
  1  findings, or an ignore-audit tag that no longer says something true
  2  self-check failed -- the scan is BROKEN and its result means nothing
  9  usage error

The inventory never lives in this repo. Resolution order:
  $KTP_SECRET_INVENTORY  ->  ~/.ktp/secret-inventory.txt
One `tag<TAB>value` per line; `#` comments and blanks ignored. Tags are `live`
(rotate if leaked) and `retired` (no longer authenticates, but still marks a
commit as having leaked, so it stays in the inventory forever).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Fake value planted in tests/fixtures/secret_canary/. Public on purpose: it
# authenticates nothing, and it is what proves the matcher still works.
CANARY = "KTPCANARY-Zm9vYmFy-DO-NOT-ROTATE"

# One canary file per format. If the walker stops reading a format the selftest
# names which one, rather than silently narrowing coverage. Quoted JSON keys are
# the classic miss, so json is not optional here.
CANARY_FORMATS = ("py", "json", "ini", "sh", "yml", "md", "conf", "cfg")

EXIT_CLEAN, EXIT_FINDINGS, EXIT_BROKEN, EXIT_USAGE = 0, 1, 2, 9

MAX_READ_BYTES = 8 * 1024 * 1024
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "artifacts", "dist"}


class Broken(Exception):
    """A self-check failed. Whatever the scan reported means nothing."""


def read_text_safe(path: Path) -> str | None:
    """Text of `path`, or None when it is unreadable or too big to be a config."""
    try:
        if path.stat().st_size > MAX_READ_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise Broken(f"git {' '.join(args)} failed: {out.stderr.strip()[:200]}")
    return out.stdout


def repo_root(start: Path) -> Path:
    out = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise Broken(f"not a git repository: {start}")
    return Path(out.stdout.strip())


def inventory_path() -> Path:
    env = os.environ.get("KTP_SECRET_INVENTORY")
    return Path(env) if env else Path.home() / ".ktp" / "secret-inventory.txt"


VALID_INVENTORY_TAGS = ("live", "retired", "hostinfo")


def _parse_inventory() -> dict[str, list[str]]:
    path = inventory_path()
    if not path.is_file():
        raise Broken(
            f"inventory not found at {path}; set KTP_SECRET_INVENTORY. "
            "A missing inventory is a broken scan, not a clean one."
        )
    buckets: dict[str, list[str]] = {tag: [] for tag in VALID_INVENTORY_TAGS}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tag, _, value = line.partition("\t")
        if not value:
            tag, _, value = line.partition(" ")
        tag, value = tag.strip().lower(), value.strip()
        if not value:
            raise Broken(f"{path}:{lineno}: tag {tag!r} with no value")
        if tag not in buckets:
            raise Broken(
                f"{path}:{lineno}: unknown tag {tag!r} "
                f"(want {'/'.join(VALID_INVENTORY_TAGS)})"
            )
        buckets[tag].append(value)
    return buckets


def load_inventory() -> tuple[list[str], list[str]]:
    """Return (live, retired). Raises Broken rather than returning empty --
    an absent inventory is a broken scan, not a clean one."""
    buckets = _parse_inventory()
    if not buckets["live"]:
        raise Broken(f"inventory {inventory_path()} holds no live values")
    return buckets["live"], buckets["retired"]


def load_hostinfo() -> list[str]:
    """Fleet addresses. Unlike live values this may legitimately be empty, so it
    returns rather than raising -- the ignore audit downgrades to a warning."""
    return _parse_inventory()["hostinfo"]


def selftest(root: Path) -> None:
    """The canary must be found in every declared format, and the matcher must
    also be capable of NOT matching. Raises Broken on either failure."""
    fixtures = root / "tests" / "fixtures" / "secret_canary"
    if not fixtures.is_dir():
        raise Broken(f"canary fixtures missing at {fixtures}")

    found: set[str] = set()
    for path in iter_files(fixtures):
        text = read_text_safe(path)
        if text and CANARY in text:
            found.add(path.suffix.lstrip("."))

    missing = [fmt for fmt in CANARY_FORMATS if fmt not in found]
    if missing:
        raise Broken(
            "canary not found in: " + ", ".join(missing)
            + " -- the walker has stopped reading those formats, so any clean "
            "result is false"
        )
    if CANARY in "nothing to see here":
        raise Broken("negative control matched -- the matcher yields false positives")


def scan_tree(root: Path, needles: list[str]) -> list[tuple[str, str]]:
    tracked = [p for p in git(root, "ls-files", "-z").split("\0") if p]
    if not tracked:
        raise Broken("git ls-files enumerated nothing -- scope is empty")
    findings = []
    for rel in tracked:
        text = read_text_safe(root / rel)
        if text is None:
            continue
        findings += [(rel, n) for n in needles if n in text]
    return findings


def value_in_tree(root: Path, sha: str, value: str) -> bool:
    """Is `value` present in the tree AT `sha` (as opposed to merely changing
    count there)? `git grep` exits 1 for no-match, which is not an error."""
    out = subprocess.run(
        ["git", "-C", str(root), "grep", "-I", "--quiet", "-F", value, sha],
        capture_output=True, text=True,
    )
    return out.returncode == 0


def _pickaxe(root: Path, needles: list[str], *log_args: str) -> list[tuple[str, str, bool]]:
    """(sha, value, present_in_tree) for each commit whose occurrence count moved.

    `git log -S` matches a commit that ADDS a value and one that REMOVES it
    alike. Both are worth blocking -- a removal proves the value is in an
    ancestor -- but they need different fixes, so classify rather than conflate.
    """
    findings = []
    for value in needles:
        for sha in git(root, "log", "--format=%H", "-S", value, *log_args).split():
            findings.append((sha, value, value_in_tree(root, sha, value)))
    return findings


def scan_range(root: Path, rev_range: str, needles: list[str]):
    """Pickaxe a commit range. This is the pre-push gate, and the reason it
    scans a range rather than staged content: the data-server root password
    entered history three days before it left the tip, and every push in
    between carried it."""
    commits = [c for c in git(root, "rev-list", rev_range).split() if c]
    if not commits:
        print(f"  range {rev_range}: no commits, nothing to scan")
        return []
    print(f"  range {rev_range}: {len(commits)} commit(s)")
    return _pickaxe(root, needles, rev_range)


def scan_history(root: Path, needles: list[str]):
    if not git(root, "rev-list", "--all", "--max-count=1").split():
        raise Broken("repository has no reachable commits -- scope is empty")
    return _pickaxe(root, needles, "--all")


def redact(value: str) -> str:
    return f"{value[:4]}...{value[-2:]} (len {len(value)})"


def report(findings, kind: str) -> int:
    """findings are (where, value) for file scans, or (sha, value, in_tree) for
    commit scans."""
    if not findings:
        print(f"  {kind}: clean (self-checks passed)")
        return EXIT_CLEAN
    print(f"  {kind}: {len(findings)} FINDING(S)")
    for finding in findings:
        if len(finding) == 3:
            sha, value, in_tree = finding
            if in_tree:
                note = "PRESENT in this commit's tree"
            else:
                note = "removed here -- so it is still in an ANCESTOR commit"
            print(f"    {sha}  <-  {redact(value)}  [{note}]")
        else:
            where, value = finding
            print(f"    {where}  <-  {redact(value)}")
    return EXIT_FINDINGS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Value-based secret scanner for KTP repos.")
    ap.add_argument("mode", choices=("tree", "range", "history", "selftest", "audit-ignore"))
    ap.add_argument("--range", help="commit range for mode=range, e.g. origin/main..HEAD")
    ap.add_argument("--repo", default=".", help="repository path (default: cwd)")
    ap.add_argument("--include-retired", action="store_true",
                    help="also scan for retired values (leak evidence; noisy on history)")
    ap.add_argument("--strict", action="store_true",
                    help="audit-ignore: promote warnings to failures")
    ap.add_argument("--structure-only", action="store_true",
                    help="audit-ignore: tags and why: lines only. Required in CI, "
                         "where the ignored files are absent by definition.")
    args = ap.parse_args(argv)

    try:
        root = repo_root(Path(args.repo).resolve())
        print(f"ktp-secret-scan: {args.mode} in {root}")

        # Self-checks run before every mode. A broken probe is not a pass.
        selftest(root)
        print(f"  selftest: canary found in all {len(CANARY_FORMATS)} formats")
        if args.mode == "selftest":
            return EXIT_CLEAN

        if args.mode == "audit-ignore":
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from ktp_ignore_audit import audit
            return audit(root, strict=args.strict,
                         structure_only=args.structure_only)

        live, retired = load_inventory()
        needles = live + (retired if args.include_retired else [])
        print(f"  inventory: {len(live)} live, {len(retired)} retired "
              f"({len(needles)} value(s) in scope)")

        if args.mode == "tree":
            return report(scan_tree(root, needles), "tracked tree")
        if args.mode == "history":
            return report(scan_history(root, needles), "history (all refs)")
        if args.mode == "range":
            if not args.range:
                print("--range is required for mode=range", file=sys.stderr)
                return EXIT_USAGE
            return report(scan_range(root, args.range, needles), f"range {args.range}")

    except Broken as exc:
        print(f"  BROKEN: {exc}", file=sys.stderr)
        print("  exit 2 -- this scan proves nothing; fix it before trusting a green build",
              file=sys.stderr)
        return EXIT_BROKEN

    return EXIT_USAGE


if __name__ == "__main__":
    # Delegate to the module under its real name. Run directly, this file is
    # `__main__`, while ktp_ignore_audit does `from ktp_secret_scan import ...`
    # and gets a SECOND copy -- two Broken classes, and `except Broken` here
    # silently fails to catch the one that was raised.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ktp_secret_scan

    sys.exit(ktp_secret_scan.main())
