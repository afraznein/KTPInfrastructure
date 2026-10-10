#!/usr/bin/env python3
"""Compare a PR's required contexts against what actually reported for its HEAD sha.

A MISSING required check and a FAILING one are indistinguishable from the PR page.
Both render as "blocked"; neither shows red. On 2026-10-05 a push to
`afraznein/KTPAntiCheat`#522 delivered no `synchronize` event -- eight of ten
workflows never saw the new sha, the two that ran were triggered by a PR-BODY EDIT
because they are the only two whose `types:` list includes `edited`, and the PR sat
BLOCKED on two required contexts that had simply never been reported. Nothing
failed, nothing queued, nothing waited, Actions permissions were enabled. A path
filter cannot explain it: `dotnet tests` has a bare `pull_request:` with no paths
at all and still never fired.

THE ONE THING THAT DISTINGUISHES THEM IS THE PER-SHA RUN LIST, so this compares
exactly that -- the required contexts on the base branch against the check-runs and
commit statuses recorded for the PR's own HEAD sha.

WHAT THIS DECIDES, AND WHAT IT REFUSES TO IMPLY.

  DECIDABLE   "every required context has reported success FOR THIS SHA"
              -> yes, from the API, which is the only place the distinction lives.
  NOT DECIDED "the checks that ran were the right checks", or that a required
              context's name still matches the job that produces it. A context
              renamed on one side and not the other reports MISSING here, which is
              the correct and useful answer, but this tool cannot tell you which
              side is wrong.

A clean exit means every required context reported success on this sha. It does NOT
mean the PR is mergeable: reviews, conversations and merge conflicts are separate
gates this does not read.

TWO TRAPS THIS SCRIPT EXISTS TO AVOID REPEATING.

  1. `gh pr view --json statusCheckRollup` returns SUPERSEDED runs alongside live
     ones, so a re-run leaves two entries per name and reading the first answers
     about whichever the API happened to order first. Every context here is
     resolved to its LATEST attempt by completion time before being judged.
  2. A required context can be produced by an Actions check-run OR by a commit
     status from an external reporter, and the two live at different endpoints.
     Reading only one reports MISSING for something that reported fine. Both are
     fetched and unioned.

THE REMEDY, WHEN A CONTEXT IS MISSING, IS NOT `gh run rerun` -- a manual re-run
replays the stale payload and re-reports against the old sha. Close and reopen the
PR: that emits `reopened`, which a bare `pull_request:` and a `paths:`-only filter
both accept, since both default to `opened, synchronize, reopened`.

Exit codes are deliberately distinct, because "I could not tell" must not read as
"it is fine":

  0  every required context reported success on this sha
  1  at least one required context is MISSING, FAILING or PENDING
  2  usage or API error
  3  UNDECIDABLE -- branch protection could not be read (see --help on 403)

On a PRIVATE repo on the free plan, `branches/<base>/protection` answers 403
"Upgrade to GitHub Pro...", and `branches/<base>` reports `protected: false`.
Protection there is not pending, it is unavailable, so this exits 3 rather than
claiming zero required contexts -- an empty required set and an unreadable one
would otherwise both look like "nothing to check".
"""
import argparse
import json
import subprocess
import sys

# conclusions GitHub itself treats as satisfying a required context
PASSING = frozenset({"success", "neutral", "skipped"})
FAILING = frozenset({"failure", "cancelled", "timed_out", "action_required",
                     "stale", "startup_failure"})

MISSING = "MISSING"
PENDING = "PENDING"
FAILED = "FAILING"
PASSED = "PASSING"


class ApiError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def gh_api(path, paginate=False):
    """One `gh api` call. Raises ApiError carrying the HTTP status, if any."""
    cmd = ["gh", "api", path]
    if paginate:
        # --slurp keeps paginated pages as a JSON array rather than concatenated
        # objects, which json.loads cannot read.
        cmd += ["--paginate", "--slurp"]
    # encoding is explicit: text=True decodes with the locale codec, and cp1252
    # raises on any UTF-8 body -- a PR title with an em dash is enough.
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        status = None
        for code in ("403", "404", "401", "301"):
            if "HTTP %s" % code in err:
                status = int(code)
                break
        raise ApiError(status, err or "gh api failed: %s" % path)
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError as exc:
        raise ApiError(None, "unparseable response from %s: %s" % (path, exc))


def _pages(value):
    """Flatten a --slurp array of pages, or wrap a single un-paginated response."""
    return value if isinstance(value, list) else [value]


def required_contexts(repo, base):
    """Required contexts on the base branch, or raise ApiError(403) if unreadable."""
    data = gh_api("repos/%s/branches/%s/protection" % (repo, base))
    checks = (data or {}).get("required_status_checks") or {}
    # `checks` carries app ids too; `contexts` is the flat name list and is still
    # the authoritative set for both classic protection and rulesets.
    names = list(checks.get("contexts") or [])
    for entry in checks.get("checks") or []:
        if entry.get("context") and entry["context"] not in names:
            names.append(entry["context"])
    return names


def reported_runs(repo, sha):
    """Every (name, status, conclusion, finished) reported for this sha.

    Unions Actions check-runs with commit statuses: a required context may be
    produced by either, and they live at different endpoints.
    """
    runs = []
    for page in _pages(gh_api("repos/%s/commits/%s/check-runs?per_page=100"
                              % (repo, sha), paginate=True)):
        for run in (page or {}).get("check_runs") or []:
            runs.append({
                "name": run.get("name"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "finished": run.get("completed_at") or run.get("started_at") or "",
                "source": "check-run",
            })
    for page in _pages(gh_api("repos/%s/statuses/%s?per_page=100" % (repo, sha),
                              paginate=True)):
        for st in page or []:
            state = st.get("state")
            runs.append({
                "name": st.get("context"),
                "status": "completed" if state != "pending" else "in_progress",
                "conclusion": {"success": "success", "failure": "failure",
                               "error": "failure"}.get(state),
                "finished": st.get("updated_at") or st.get("created_at") or "",
                "source": "status",
            })
    return runs


def latest_per_name(runs):
    """Collapse re-runs to the newest attempt per context name.

    This is the superseded-run trap: both attempts are returned by the API and
    whichever comes first in the response is not necessarily the live one.
    """
    newest = {}
    for run in runs:
        name = run.get("name")
        if not name:
            continue
        prior = newest.get(name)
        if prior is None or (run.get("finished") or "") >= (prior.get("finished") or ""):
            newest[name] = run
    return newest


def classify(required, runs):
    """Pure: required context names + reported runs -> {name: state}.

    Separated from every API call on purpose, so the judgement is testable without
    a network and without a repo that happens to be in the interesting state.
    """
    newest = latest_per_name(runs)
    verdict = {}
    for name in required:
        run = newest.get(name)
        if run is None:
            verdict[name] = MISSING
        elif run.get("status") != "completed" or run.get("conclusion") is None:
            verdict[name] = PENDING
        elif run["conclusion"] in PASSING:
            verdict[name] = PASSED
        elif run["conclusion"] in FAILING:
            verdict[name] = FAILED
        else:
            verdict[name] = PENDING
    return verdict


def report(repo, pr, sha, verdict, extra, out=None):
    # Resolved per call, not bound as a default: a default captures the stdout that
    # existed at import and writes past any later redirection.
    out = sys.stdout if out is None else out
    order = {MISSING: 0, FAILED: 1, PENDING: 2, PASSED: 3}
    print("%s#%s  HEAD %s" % (repo, pr, sha), file=out)
    if not verdict:
        print("  no required contexts on the base branch", file=out)
    for name in sorted(verdict, key=lambda n: (order[verdict[n]], n)):
        print("  %-8s %s" % (verdict[name], name), file=out)
    missing = [n for n, v in verdict.items() if v == MISSING]
    if missing:
        print("\n  %d required context(s) NEVER REPORTED for this sha." % len(missing),
              file=out)
        print("  This is not a failure and will not show red. Close and reopen the"
              " PR to\n  re-trigger on a fresh payload; do NOT `gh run rerun`,"
              " which replays the\n  stale one.", file=out)
    if extra:
        print("\n  also reported, not required: %s" % ", ".join(sorted(extra)),
              file=out)
    return missing


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Compare a PR's required contexts against what reported for "
                    "its HEAD sha.",
        epilog="Exit 0 all required contexts passed; 1 missing/failing/pending; "
               "2 usage or API error; 3 branch protection unreadable (a PRIVATE "
               "repo on the free plan answers 403 and is genuinely undecidable).")
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--pr", required=True, type=int)
    ap.add_argument("--show-extra", action="store_true",
                    help="also list contexts that reported but are not required")
    args = ap.parse_args(argv)

    try:
        pull = gh_api("repos/%s/pulls/%d" % (args.repo, args.pr))
    except ApiError as exc:
        print("error: cannot read %s#%d: %s" % (args.repo, args.pr, exc),
              file=sys.stderr)
        return 2
    if not isinstance(pull, dict):
        print("error: %s#%d returned no object; an empty body is not an empty PR"
              % (args.repo, args.pr), file=sys.stderr)
        return 2
    sha = (pull.get("head") or {}).get("sha")
    base = (pull.get("base") or {}).get("ref")
    if not sha or not base:
        print("error: %s#%d has no head sha or base ref" % (args.repo, args.pr),
              file=sys.stderr)
        return 2

    try:
        required = required_contexts(args.repo, base)
    except ApiError as exc:
        if exc.status == 403:
            print("UNDECIDABLE: branch protection on %s:%s is unreadable (403)."
                  % (args.repo, base), file=sys.stderr)
            print("A private repo on the free plan cannot have protection; an "
                  "unreadable required\nset is not an empty one, so this is not "
                  "reported as a pass.", file=sys.stderr)
            return 3
        if exc.status == 404:
            required = []
        else:
            print("error: cannot read protection on %s:%s: %s"
                  % (args.repo, base, exc), file=sys.stderr)
            return 2

    try:
        runs = reported_runs(args.repo, sha)
    except ApiError as exc:
        print("error: cannot read checks for %s: %s" % (sha, exc), file=sys.stderr)
        return 2

    verdict = classify(required, runs)
    extra = (set(latest_per_name(runs)) - set(required)) if args.show_extra else set()
    report(args.repo, args.pr, sha, verdict, extra)
    return 0 if all(v == PASSED for v in verdict.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
