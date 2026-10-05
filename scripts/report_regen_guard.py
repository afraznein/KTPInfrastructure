"""Preconditions for the gated report-regeneration workflow.

The workflow (.github/workflows/report-regeneration.yml) runs on the tier-2
runner, which is root on the production data server. Every check here fails
closed: a precondition that cannot be proved is a refusal, never a pass.

  inputs    validate the dispatch inputs; write the match ids, one per line
  checkout  fetch-only refresh of the serving checkout, then refuse unless it
            is clean and HEAD == fetched origin/main == the dispatched commit
  floor     the season --since floor the INSTALLED unit runs with
  window    refuse when the report timer fires too soon to finish before it

Exit: 0 ok, 1 refused, 2 could not check.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SCOPES = ("pending", "match_ids")
MATCH_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
MAX_MATCH_IDS = 25
MAX_REASON = 300
SINCE_RE = re.compile(
    r"^ExecStart=.*\breport_service\s+--repo\s+\S+\s+generate\b.*?--since\s+"
    r"(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?)", re.MULTILINE)


class Refused(Exception):
    pass


def validate_inputs(scope: str, match_ids: str, reason: str) -> list[str]:
    if scope not in SCOPES:
        raise Refused(f"scope must be one of {', '.join(SCOPES)}, got {scope!r}")
    if not reason.strip():
        raise Refused("reason is required; it is the record of why this ran")
    if len(reason) > MAX_REASON:
        raise Refused(f"reason is longer than {MAX_REASON} characters")
    ids = [t for t in re.split(r"[\s,]+", match_ids.strip()) if t]
    if scope == "pending":
        if ids:
            raise Refused("match_ids given with scope=pending; pick match_ids "
                          "or clear the field")
        return []
    if not ids:
        raise Refused("scope=match_ids needs at least one match id")
    if len(ids) > MAX_MATCH_IDS:
        raise Refused(f"more than {MAX_MATCH_IDS} match ids; use scope=pending "
                      "or split the run")
    bad = [i for i in ids if not MATCH_ID_RE.fullmatch(i)]
    if bad:
        raise Refused(f"{len(bad)} match id(s) are not a match-id shape")
    return list(dict.fromkeys(ids))


def _git(repo: Path, as_user: str | None, *args: str) -> str:
    # Root's git refuses a repository it does not own, so run as the owner.
    prefix = ["runuser", "-u", as_user, "--"] if as_user else []
    proc = subprocess.run([*prefix, "git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {proc.stderr.strip()[-400:]}")
    return proc.stdout.strip()


def check_checkout(repo: Path, expect_sha: str, as_user: str | None = None,
                   remote: str = "origin", branch: str = "main") -> str:
    """Fetch only, never checkout/merge/pull, then refuse a tree that is not
    exactly reviewed main. Returns the verified commit."""
    if not re.fullmatch(r"[0-9a-f]{40}", expect_sha):
        raise Refused(f"expected commit is not a full sha: {expect_sha!r}")
    head_before = _git(repo, as_user, "rev-parse", "--verify", "HEAD")
    # --refmap= stops the configured refspec from also writing refs/heads/*.
    _git(repo, as_user, "fetch", "--quiet", "--no-tags", "--refmap=", remote,
         f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}")
    head = _git(repo, as_user, "rev-parse", "--verify", "HEAD")
    if head != head_before:
        raise Refused("HEAD moved during the fetch; something else is writing "
                      "the serving checkout")
    dirty = _git(repo, as_user, "status", "--porcelain", "--untracked-files=normal")
    if dirty:
        raise Refused(f"serving checkout is dirty ({len(dirty.splitlines())} "
                      "path(s)); regenerate only from a clean tree")
    upstream = _git(repo, as_user, "rev-parse", "--verify",
                    f"refs/remotes/{remote}/{branch}^{{commit}}")
    if head != upstream:
        raise Refused(f"serving checkout HEAD {head[:12]} is not fetched "
                      f"{remote}/{branch} {upstream[:12]}; bring it to main "
                      "first (this workflow never moves it)")
    if expect_sha != upstream:
        raise Refused(f"dispatched commit {expect_sha[:12]} is not "
                      f"{remote}/{branch} {upstream[:12]}; dispatch from the "
                      "current main")
    return head


def unit_floor(unit_text: str) -> str:
    # Last match: `systemctl cat` prints drop-ins after the unit, and they win.
    found = SINCE_RE.findall(unit_text)
    if not found:
        raise Refused("no `generate --since` floor in the installed unit; "
                      "refusing to guess the season boundary")
    return found[-1]


def check_window(now: int, next_tick: int, need_sec: int) -> int:
    """Seconds until the timer's next tick, or Refused when too few remain."""
    if next_tick <= 0:
        raise Refused("report timer has no next elapse; is it enabled?")
    left = next_tick - now
    if left < need_sec:
        raise Refused(f"report timer fires in {max(left, 0)}s and this run "
                      f"needs {need_sec}s clear of it; dispatch again after it")
    return left


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inputs")
    p.add_argument("--scope", required=True)
    p.add_argument("--match-ids", default="")
    p.add_argument("--reason", default="")
    p.add_argument("--ids-out", type=Path, required=True)
    p = sub.add_parser("checkout")
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--expect-sha", required=True)
    p.add_argument("--as-user", default=None)
    p = sub.add_parser("floor")
    p = sub.add_parser("window")
    p.add_argument("--now", type=int, required=True)
    p.add_argument("--next-tick", type=int, required=True)
    p.add_argument("--need-sec", type=int, required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "inputs":
            ids = validate_inputs(args.scope, args.match_ids, args.reason)
            args.ids_out.write_text("".join(f"{i}\n" for i in ids), encoding="utf-8")
            print(f"inputs ok: scope={args.scope}, match ids={len(ids)}")
        elif args.cmd == "checkout":
            sha = check_checkout(args.repo, args.expect_sha, args.as_user)
            print(f"checkout ok: clean, at origin/main {sha}")
        elif args.cmd == "floor":
            print(unit_floor(sys.stdin.read()))
        else:
            left = check_window(args.now, args.next_tick, args.need_sec)
            print(f"window ok: report timer next fires in {left}s")
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    except (RuntimeError, OSError) as exc:
        print(f"could not check: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
