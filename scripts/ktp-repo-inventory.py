#!/usr/bin/env python3
"""Enumerate the KTP estate's branches, open PRs and open issues, live, per repo.

This exists because the figures used to live in prose. A board card carried a
hand-typed inventory of every repo's open issues and PRs; it rotted five times
between 2026-09-04 and 2026-10-06, twice within hours of being written, and each
rewrite was indistinguishable from a fresh reading. Re-deriving on demand is the
only form of this answer that cannot go stale, so the answer belongs in a command.

WHAT THIS DECIDES, AND WHAT IT REFUSES TO IMPLY.

  DECIDABLE   "at the moment of this run, repo R has these refs, these open PRs
              and these open issues"
              -> yes, straight from the per-repo API endpoints.
  NOT DECIDED whether any branch is safe to delete. Merge state needs the branch
              tip tested against the PR's headRefOid and THEN content, and the
              deletion itself is ruled operator-only. --compare prints ahead/behind
              and flags orphans; it proposes nothing, by design.

FIVE TRAPS THIS ENCODES, EACH MEASURED BEFORE IT WAS WRITTEN DOWN.

  1. `gh search prs` lags its index by minutes and reported a merged PR as open.
     Every PR and issue read here is a per-repo `gh api repos/<o>/<r>/...` call.
  2. A branch list read from a local checkout over-reports and does so silently:
     `git fetch` does not prune, so a deleted remote branch survives as a
     tracking ref indefinitely -- three `origin/*` refs locally against one on
     the remote, in one repo. Refs come from the API only.
  3. An ORPHAN branch makes `compare` answer 404 "No common ancestor", which
     reads as a failed probe rather than as the finding it is. Under --compare
     that 404 is classified ORPHAN and reported, never swallowed.
  4. `ahead_by > 0` is not evidence of unmerged work: the deploy train squashes,
     so a fully merged branch still reports commits the default branch "lacks".
  5. A repo whose call fails must never render as a repo with nothing in it.
     Any failure is printed as ERROR, counted apart from the zeros, and exits 2.
  6. `users/<owner>/repos` omits PRIVATE repos and says nothing about it. The
     first run of this script read 24 of the estate's 34 repos and rendered a
     complete-looking table; the ten it dropped were the private ones, and the
     positive control below could not see it because the repos it DID read
     answered normally. The authenticated `/user/repos` is used instead whenever
     the owner is the viewer, and the public listing is read anyway as a subset
     check.

THE ZEROS ARE READINGS ONLY IF THE CONTROLS PASS, so they run every time:

  positive     every repo has at least a default branch, so a branch sweep that
               returns zero refs everywhere is a broken probe, not an empty
               estate.
  negative     two names that cannot exist must ERROR rather than answer empty.
  completeness the public owner listing must be a subset of the listing actually
               swept, so a visibility-filtered read cannot pass as the estate.

All three are checked before any count is printed, and a control failure exits 3
-- "I could not tell" must not read as "there is nothing there".

THE REPO SET IS DERIVED, NOT TYPED. `gh repo list <owner>` plus a --match filter
is the whole of it. Two repos belong to the estate and to other accounts, so they
cannot come out of an owner listing; they are the only names spelled out here, and
--extra-repo adds more without a code change.

  0  inventory read; controls passed
  2  at least one repo could not be read, or a usage error
  3  UNDECIDABLE -- a control failed, so the counts are not readings
"""
import argparse
import json
import subprocess
import sys

DEFAULT_OWNER = "afraznein"
DEFAULT_MATCH = "KTP"

# Estate repos under other accounts. An owner listing cannot produce these, so
# they are named; nothing else in this file is.
FOREIGN_REPOS = ("searse/keep-the-prac", "andsmit9/ktp-coordination")

# Refs a sweep keeps proposing and must not. Each is load-bearing and none of
# them is reachable from the default branch, which is exactly why they look
# deletable: `production` carries what is deployed, `deploy/train` is the
# mechanism, and `mmr-ratings` is bot-written weekly data with no common
# ancestor at all.
GUARDED_REFS = {
    "searse/keep-the-prac": ("production", "deploy/train"),
    "afraznein/KTPInfrastructure": ("mmr-ratings",),
}

# Two names that cannot exist. The probe must error on both; an empty answer here
# means it would also answer empty for a repo that does exist.
CONTROL_REPOS = ("afraznein/KTPNoSuchRepoControlA",
                 "afraznein/KTPNoSuchRepoControlB")


class ApiError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def gh_api(path, paginate=False):
    """One `gh api` call. Raises ApiError carrying the HTTP status, if any."""
    cmd = ["gh", "api", path]
    if paginate:
        # --slurp keeps pages as a JSON array; without it json.loads cannot read
        # concatenated objects.
        cmd += ["--paginate", "--slurp"]
    # encoding is explicit: text=True decodes with the locale codec, and cp1252
    # raises on any UTF-8 body -- one em dash in a PR title is enough.
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        status = None
        for code in ("403", "404", "401", "301", "451"):
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


def _flat(value):
    """Flatten a paginated list-of-lists into one list of items."""
    out = []
    for page in _pages(value):
        for item in page or []:
            out.append(item)
    return out


def _select(listed, owner, match):
    """Filter a repo listing to the live estate repos under one owner."""
    names = []
    for repo in listed:
        name = repo.get("name") or ""
        if not name or repo.get("archived"):
            continue
        if match and match.lower() not in name.lower():
            continue
        names.append("%s/%s" % (owner, name))
    return names


def owner_listing(api, owner, match, viewer):
    """Repos under `owner`, with a completeness control on the listing itself.

    `users/<owner>/repos` returns PUBLIC repos only, and it does so silently --
    a token with full access to ten private estate repos still gets a listing
    without them, and the result reads as a complete inventory. The authenticated
    `/user/repos` endpoint is the one that includes them, so it is used whenever
    the owner IS the viewer. The public listing is then read as well and must be a
    SUBSET: a public repo missing from the chosen listing means the listing is not
    the thing it claims to be, and that is reported rather than counted.

    Returns (names, complete, lines).
    """
    lines = []
    public = _select(_flat(api("users/%s/repos?per_page=100&type=owner" % owner,
                               paginate=True)), owner, match)
    if viewer and viewer.lower() == owner.lower():
        chosen = _select(_flat(api("user/repos?per_page=100&affiliation=owner",
                                   paginate=True)), owner, match)
        private_seen = len(set(chosen) - set(public))
        lines.append("control  owner listing is the authenticated one; %d repos "
                     "the public listing cannot see" % private_seen)
    else:
        chosen = public
        lines.append("control  owner %s is not the viewer, so this listing is "
                     "PUBLIC-ONLY; private repos there are invisible" % owner)
    missing = sorted(set(public) - set(chosen))
    if missing:
        lines.append("control  FAILED: public listing is not a subset -- %s"
                     % ", ".join(missing))
        return chosen, False, lines
    return chosen, True, lines


def repo_set(api, owner, match, extra, include_foreign=True, viewer=None):
    """Repos to sweep: a derived owner listing plus the named outsiders.

    Returns (names, complete, lines) -- `complete` False means do not count.
    """
    chosen, complete, lines = owner_listing(api, owner, match, viewer)
    names = list(chosen)
    if include_foreign:
        names.extend(FOREIGN_REPOS)
    names.extend(extra or ())
    # dedupe, keep first-seen order
    seen, ordered = set(), []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered, complete, lines


def read_repo(api, full_name):
    """Branches, open PRs and open issues for one repo. Raises ApiError."""
    meta = api("repos/%s" % full_name)
    default = (meta or {}).get("default_branch") or ""
    branches = [b.get("name") for b
                in _flat(api("repos/%s/branches?per_page=100" % full_name,
                             paginate=True))
                if b.get("name")]
    pulls = [{"number": p.get("number"), "head": (p.get("head") or {}).get("ref")}
             for p in _flat(api("repos/%s/pulls?state=open&per_page=100"
                                % full_name, paginate=True))]
    # The issues endpoint returns PRs too -- every PR is an issue. Filtering on
    # the `pull_request` key is what keeps a PR out of the issue count; the
    # `gh issue list` command does the same thing one layer up.
    issues = [i.get("number") for i
              in _flat(api("repos/%s/issues?state=open&per_page=100" % full_name,
                           paginate=True))
              if i.get("number") and "pull_request" not in i]
    return {
        "repo": full_name,
        "private": bool((meta or {}).get("private")),
        "default_branch": default,
        "branches": branches,
        "non_default": [b for b in branches if b != default],
        "open_prs": pulls,
        "open_issues": issues,
    }


def annotate(row):
    """Per-branch notes: nothing here is a deletion proposal."""
    guarded = set(GUARDED_REFS.get(row["repo"], ()))
    pr_heads = {p["head"] for p in row["open_prs"] if p.get("head")}
    notes = {}
    for branch in row["non_default"]:
        tags = []
        if branch in guarded:
            tags.append("GUARDED")
        if branch in pr_heads:
            tags.append("open-PR-head")
        notes[branch] = tags
    return notes


def compare_branch(api, full_name, base, branch):
    """ahead/behind for one branch, with the orphan 404 classified not swallowed."""
    try:
        data = api("repos/%s/compare/%s...%s" % (full_name, base, branch))
    except ApiError as exc:
        if exc.status == 404 and "common ancestor" in str(exc).lower():
            return {"state": "ORPHAN", "ahead": None, "behind": None}
        if exc.status == 404:
            # a 404 with no ancestor wording is a different animal: the ref or the
            # base is gone. Report it, do not fold it into ORPHAN.
            return {"state": "UNREADABLE-404", "ahead": None, "behind": None}
        raise
    return {"state": "compared",
            "ahead": data.get("ahead_by"),
            "behind": data.get("behind_by")}


def run_controls(api):
    """Returns (ok, lines). Zeros are not readings until this passes."""
    lines, ok = [], True
    for name in CONTROL_REPOS:
        try:
            api("repos/%s/branches?per_page=1" % name)
        except ApiError as exc:
            lines.append("control  %-44s ERRORED as required (%s)"
                         % (name, exc.status or "no status"))
        else:
            ok = False
            lines.append("control  %-44s ANSWERED -- a nonexistent repo must not"
                         % name)
    return ok, lines


def positive_control(rows):
    """A branch sweep returning zero refs everywhere is a broken probe."""
    total = sum(len(r["branches"]) for r in rows)
    return total > 0, total


def render_text(rows, notes, compares, out):
    width = max([len(r["repo"]) for r in rows] + [4])
    print("%-*s  %-8s  %-18s  %5s  %4s  %6s"
          % (width, "repo", "vis", "default", "refs", "PRs", "issues"), file=out)
    for row in rows:
        print("%-*s  %-8s  %-18s  %5d  %4d  %6d"
              % (width, row["repo"],
                 "private" if row["private"] else "public",
                 row["default_branch"],
                 len(row["non_default"]),
                 len(row["open_prs"]),
                 len(row["open_issues"])), file=out)
        for branch in row["non_default"]:
            tags = list(notes.get(row["repo"], {}).get(branch, []))
            cmp_ = (compares.get(row["repo"]) or {}).get(branch)
            if cmp_:
                if cmp_["state"] == "compared":
                    tags.append("ahead %s / behind %s"
                                % (cmp_["ahead"], cmp_["behind"]))
                else:
                    tags.append(cmp_["state"])
            print("%-*s    ref  %s%s"
                  % (width, "", branch, ("  [%s]" % ", ".join(tags)) if tags else ""),
                  file=out)
        if row["open_prs"]:
            print("%-*s    PRs  %s"
                  % (width, "", " ".join("#%s" % p["number"]
                                         for p in row["open_prs"])), file=out)
        if row["open_issues"]:
            print("%-*s   isss  %s"
                  % (width, "", " ".join("#%s" % n for n in row["open_issues"])),
                  file=out)


def render_tsv(rows, notes, compares, out):
    print("repo\tvisibility\tdefault_branch\tnon_default_refs\topen_prs"
          "\topen_issues\tguarded\tbranches", file=out)
    for row in rows:
        guarded = [b for b, tags in (notes.get(row["repo"]) or {}).items()
                   if "GUARDED" in tags]
        print("\t".join([
            row["repo"],
            "private" if row["private"] else "public",
            row["default_branch"],
            str(len(row["non_default"])),
            ",".join(str(p["number"]) for p in row["open_prs"]),
            ",".join(str(n) for n in row["open_issues"]),
            ",".join(sorted(guarded)),
            ",".join(row["non_default"]),
        ]), file=out)


# ---------------------------------------------------------------- selftest ----

def _fake_api(table):
    """An api() over a dict of path -> value or ApiError, for the selftest."""
    def api(path, paginate=False):
        if path not in table:
            raise ApiError(404, "HTTP 404: Not Found (%s)" % path)
        value = table[path]
        if isinstance(value, ApiError):
            raise value
        return value
    return api


def selftest():
    """Fixtures that must fail if the logic inverts. Judged on output, not exit."""
    failures = []
    ran = []

    def check(name, got, want):
        ran.append(name)
        if got != want:
            failures.append("%s: got %r want %r" % (name, got, want))

    # the issues endpoint returns PRs; a PR must not land in the issue count
    api = _fake_api({
        "repos/o/r": {"default_branch": "main", "private": False},
        "repos/o/r/branches?per_page=100": [[{"name": "main"},
                                             {"name": "feature/x"}]],
        "repos/o/r/pulls?state=open&per_page=100": [[{"number": 7,
                                                      "head": {"ref": "feature/x"}}]],
        "repos/o/r/issues?state=open&per_page=100": [[
            {"number": 7, "pull_request": {"url": "..."}},
            {"number": 9},
        ]],
    })
    row = read_repo(api, "o/r")
    check("issues exclude PRs", row["open_issues"], [9])
    check("non_default excludes default", row["non_default"], ["feature/x"])

    # an open PR's head branch is annotated, never silently countable as stale
    notes = annotate(dict(row, repo="o/r"))
    check("open PR head annotated", notes["feature/x"], ["open-PR-head"])

    # the guard list reaches the repo it names and no other
    guarded = annotate({"repo": "searse/keep-the-prac",
                        "non_default": ["production", "feature/y"],
                        "open_prs": []})
    check("guard hits production", guarded["production"], ["GUARDED"])
    check("guard misses sibling", guarded["feature/y"], [])
    unguarded = annotate({"repo": "o/r", "non_default": ["production"],
                          "open_prs": []})
    check("guard is per repo", unguarded["production"], [])

    # the orphan 404 is a finding; any other 404 is a different finding; a 403
    # is neither and must propagate
    orphan = _fake_api({"repos/o/r/compare/main...orph":
                        ApiError(404, "HTTP 404: No common ancestor between "
                                      "main and orph")})
    check("orphan classified",
          compare_branch(orphan, "o/r", "main", "orph")["state"], "ORPHAN")
    gone = _fake_api({"repos/o/r/compare/main...gone":
                      ApiError(404, "HTTP 404: Not Found")})
    check("plain 404 not orphan",
          compare_branch(gone, "o/r", "main", "gone")["state"], "UNREADABLE-404")
    denied = _fake_api({"repos/o/r/compare/main...x": ApiError(403, "HTTP 403")})
    ran.append("403 on compare propagates")
    try:
        compare_branch(denied, "o/r", "main", "x")
        failures.append("403 on compare was swallowed")
    except ApiError:
        pass

    # the negative control must fail loudly when the probe answers for a
    # nonexistent repo, and pass when it errors
    broken = _fake_api({"repos/%s/branches?per_page=1" % CONTROL_REPOS[0]: [[]],
                        "repos/%s/branches?per_page=1" % CONTROL_REPOS[1]: [[]]})
    check("negative control catches a probe that answers empty",
          run_controls(broken)[0], False)
    check("negative control passes when both error",
          run_controls(_fake_api({}))[0], True)

    # the positive control must reject an all-zero branch sweep
    check("positive control rejects zero refs everywhere",
          positive_control([{"branches": []}, {"branches": []}])[0], False)
    check("positive control accepts a real reading",
          positive_control([{"branches": ["main"]}])[0], True)

    # archived repos and non-matching names are filtered; the foreign repos are
    # not derivable and must still be present
    public_only = [[{"name": "KTPThing"}, {"name": "KTPOld", "archived": True},
                    {"name": "portfolio"}]]
    authed = [[{"name": "KTPThing"}, {"name": "KTPSecret"},
               {"name": "KTPOld", "archived": True}]]
    listing = _fake_api({"users/o/repos?per_page=100&type=owner": public_only,
                         "user/repos?per_page=100&affiliation=owner": authed})
    names, complete, _ = repo_set(listing, "o", "KTP", ("x/y",), viewer="o")
    check("repo set derived, filtered, and includes a private repo",
          names, ["o/KTPThing", "o/KTPSecret"] + list(FOREIGN_REPOS) + ["x/y"])
    check("complete listing passes the subset control", complete, True)

    # the completeness control is the one the first live run needed: a listing
    # that drops a repo the public listing has must not be counted
    truncated = _fake_api({
        "users/o/repos?per_page=100&type=owner": public_only,
        "user/repos?per_page=100&affiliation=owner": [[{"name": "KTPSecret"}]],
    })
    _, complete_bad, _ = repo_set(truncated, "o", "KTP", (), viewer="o")
    check("subset control catches a listing missing a public repo",
          complete_bad, False)

    # a foreign owner cannot be read with the authenticated endpoint, and the
    # public-only fallback must still answer rather than crash
    foreign = _fake_api({"users/other/repos?per_page=100&type=owner": public_only})
    names_f, complete_f, lines_f = repo_set(foreign, "other", "KTP", (),
                                            include_foreign=False, viewer="o")
    check("foreign owner falls back to the public listing",
          (names_f, complete_f), (["other/KTPThing"], True))
    check("foreign owner says the listing is public-only",
          any("PUBLIC-ONLY" in line for line in lines_f), True)

    for line in failures:
        print("not ok %s" % line)
    print("# %d checks, %d failed" % (len(ran), len(failures)))
    return 0 if not failures else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Live inventory of the KTP estate's refs, open PRs and issues.")
    ap.add_argument("--owner", default=DEFAULT_OWNER)
    ap.add_argument("--match", default=DEFAULT_MATCH,
                    help="substring a repo name must contain (default: KTP). "
                         "Pass an empty string for every repo the owner has.")
    ap.add_argument("--extra-repo", action="append", default=[],
                    metavar="OWNER/NAME",
                    help="sweep this repo too; repeatable")
    ap.add_argument("--no-foreign", action="store_true",
                    help="skip the estate repos owned by other accounts")
    ap.add_argument("--repo", action="append", default=[], metavar="OWNER/NAME",
                    help="sweep ONLY these; skips the owner listing")
    ap.add_argument("--compare", action="store_true",
                    help="also read ahead/behind per branch and classify orphans. "
                         "ahead_by > 0 is NOT evidence of unmerged work here -- "
                         "the deploy train squashes.")
    ap.add_argument("--tsv", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    api = gh_api

    controls_ok, control_lines = run_controls(api)
    for line in control_lines:
        print(line, file=sys.stderr)
    if not controls_ok:
        print("UNDECIDABLE: a nonexistent repo answered instead of erroring, so "
              "an empty\nresult from this probe is not a reading. Nothing counted.",
              file=sys.stderr)
        return 3

    if args.repo:
        names = args.repo
    else:
        try:
            viewer = (gh_api("user") or {}).get("login")
            names, complete, lines = repo_set(
                api, args.owner, args.match, args.extra_repo,
                include_foreign=not args.no_foreign, viewer=viewer)
        except ApiError as exc:
            print("error: cannot list repos for %s: %s" % (args.owner, exc),
                  file=sys.stderr)
            return 2
        for line in lines:
            print(line, file=sys.stderr)
        if not complete:
            print("UNDECIDABLE: the owner listing dropped repos the public "
                  "listing has, so it\nis not the estate. Nothing counted.",
                  file=sys.stderr)
            return 3

    rows, errors = [], []
    for name in names:
        try:
            rows.append(read_repo(api, name))
        except ApiError as exc:
            errors.append((name, str(exc).splitlines()[0] if str(exc) else "?"))

    pos_ok, ref_total = positive_control(rows)
    if rows and not pos_ok:
        print("UNDECIDABLE: %d repos answered and not one returned a ref. Every "
              "repo has at\nleast a default branch, so this is a broken probe, "
              "not an empty estate." % len(rows), file=sys.stderr)
        return 3

    notes = {row["repo"]: annotate(row) for row in rows}
    compares = {}
    if args.compare:
        for row in rows:
            per = {}
            for branch in row["non_default"]:
                try:
                    per[branch] = compare_branch(api, row["repo"],
                                                 row["default_branch"], branch)
                except ApiError as exc:
                    errors.append(("%s:%s" % (row["repo"], branch), str(exc)))
            compares[row["repo"]] = per

    if args.json:
        json.dump({"repos": rows, "notes": notes, "compares": compares,
                   "errors": [{"repo": r, "error": e} for r, e in errors]},
                  sys.stdout, indent=2, sort_keys=True)
        print()
    elif args.tsv:
        render_tsv(rows, notes, compares, sys.stdout)
    else:
        render_text(rows, notes, compares, sys.stdout)
        print("\n%d repos read, %d refs, %d non-default refs, %d open PRs, "
              "%d open issues"
              % (len(rows), ref_total,
                 sum(len(r["non_default"]) for r in rows),
                 sum(len(r["open_prs"]) for r in rows),
                 sum(len(r["open_issues"]) for r in rows)))
        print("controls: %d negative passed, positive passed (%d refs seen)"
              % (len(CONTROL_REPOS), ref_total))

    if errors:
        print("\nERROR -- these were NOT read, and are not zeros:",
              file=sys.stderr)
        for name, err in errors:
            print("  %-44s %s" % (name, err), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
