#!/usr/bin/env python3
"""Did THIS pull request record a decision about the analytics schema version?

WHAT WENT WRONG, MEASURED RATHER THAN IMAGINED. On 2026-10-12 two pull requests --
#693 and #696 -- corrected the report-team convention across seven analytics
consumers and did not touch `SCHEMA_VERSION` in `scripts/match_analytics.py`. That
constant is the generator's ONLY test for "already current": a stored report whose
`schema_version` equals it is skipped, whichever code produced it. So two different
analytics outputs both carried `30`. Measured on the live reports table the same
evening: 854 reports, 613 below 30 that regenerate on the timer and self-heal, 241
at 30 that are skipped -- and 237 of those 241 were generated BEFORE the merges,
all 237 distinct matches, all two-half, all carrying `positional` and
`shadow_explorations`. 237 published reports sat at the current schema carrying
pre-fix values with nothing that would ever revisit them.

AND BOTH PULL REQUESTS PASSED FULL CI GREEN, which is the whole reason this file
exists rather than a stronger test somewhere. The defect is invisible to the
obvious shape of check: `positional_shadow` lost NO rows across #696 --
`kills_located` was 565 before and 565 after -- while every value in half 1 of
every two-half match was wrong. A row-count gate passes it. A diff-shape gate
passes it. The repository's own schema 19 entry describes this exact fix class in
these words -- "translated engine-side -> report-team convention (were silently
backwards in half 1 of every two-half match)" -- so the class had a known answer
and two PRs did not apply it.

WHAT THIS ASKS, AND WHAT IT DELIBERATELY DOES NOT. It asks whether the pull
request RECORDED A DECISION, by one of exactly two routes:

  (1) its own diff bumps `SCHEMA_VERSION` in scripts/match_analytics.py, or
  (2) its own body declares, under a qualifying heading, that stored values do
      not change.

⛔ A BUMP IS NEVER EVIDENCE THE DATA IS RIGHT, and this script says so in its own
output on every pass. Bumping is one character; an author can bump and never
regenerate, and the regeneration is an operator act on another box. Route (2) is
not a weaker route either -- it is the same claim made in words instead of in a
constant, and it is the only honest one for a refactor. What a green here means is
"somebody decided, in public, and a later reader can find where". Nothing more.

WHY THE PATH IS DERIVED AND NOT LISTED. A gate keyed on `scripts/**` red-lights
docs-adjacent and test-only touches that owe nothing, and a gate that cries wolf
gets switched off -- which is strictly worse than no gate. A hand-written list of
"the analytics files" rots the first time a module is added, and it rots SILENTLY
in the permissive direction. So the output path is computed from the checkout:

  MODULES  the transitive `scripts.*` import closure rooted at the generator,
           scripts/match_analytics.py. 25 modules at f6c4aa0, and it contains
           every file #693 and #696 touched under scripts/.
  DATA     the `config/` data files those modules read. Not decoration: schema 22
           ("flag_swing reads PER-MAP coefficients from config/map_coefficients.json")
           and schema 27 ("map coefficients refitted after week 40") are both
           bumps this repository made for a change to one of these files and no
           change to any code at all.

Everything else -- tests/, docs/, changelog.d/, provision/, every other script --
is out of scope and exits 0 with the path printed, so a reader can see what the
boundary was rather than infer it.

THE SERVING LAYER IS OUT OF SCOPE, AS A DECISION. `scripts/analytics_report_dto.py`
shapes what is PUBLISHED from a stored report and is re-read on every sync, so a
change there reaches viewers without a regeneration; it is downstream of the
constant and nothing about it is skipped at schema parity. It is reached from
report_service/report_sync, never from match_analytics, so the import closure
excludes it by construction rather than by exemption.

NO EXEMPTION LIST, AND NO RATCHET FLOOR. The audit-log gates in afraznein/KTPAntiCheat
whose shape this copies carry a ratchet (`APPEND_IN_PR_FROM`) because their
convention changed under open pull requests. Measured here on 2026-10-12 before
writing this: exactly ONE open PR in this repository touches the derived path --
#697, which bumps 30 -> 31 and therefore passes -- so a floor would exempt nothing
that needs exempting and would start life as dead weight that silently widens.
If it ever is needed, it belongs here as a number with that measurement next to
it, never as a path or author list.

Usage:
    python3 scripts/check-analytics-schema-decision.py --pr N [--repo OWNER/NAME] [--root .]
    python3 scripts/check-analytics-schema-decision.py --files-json F --body-file F
    python3 scripts/check-analytics-schema-decision.py --print-path [--root .]

Exit 0: this PR is outside the analytics output path, or it recorded a decision.
Exit 1: it changes the analytics output path and records no decision either way.
Exit 2: the check could not run, or could not prove itself discriminating. Being
        unable to look is never a pass.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import traceback

# Findings quote PR bodies, which carry this estate's glyphs. A Windows console
# defaults to cp1252 and raises mid-print, truncating the finding and exiting 1.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

GENERATOR = "scripts/match_analytics.py"
VERSION_CONST = "SCHEMA_VERSION"

# A data file is one of these; the extension set is what the closure actually reads.
DATA_EXT = r"json|toml|csv|ini|ya?ml"
# `config/a/b.json` written out as one literal.
DATA_DIRECT = re.compile(r"config/[A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:%s)" % DATA_EXT)
# The same path assembled through pathlib or os.path.join -- `"config" / "x.json"`,
# `"config", "analytics", "x.toml"`. flag_swing.py loads the map coefficients this way,
# so a literal-only reader misses the one data file this repository has bumped the
# schema for TWICE.
DATA_JOINED = re.compile(
    r"""["']config["']\s*(?:/|,)\s*"""
    r"""(?:["'][A-Za-z0-9_.-]+["']\s*(?:/|,)\s*)*"""
    r"""["']([A-Za-z0-9_./-]+\.(?:%s))["']""" % DATA_EXT
)

# The bump, read off the PR's OWN diff. The leading `+`/`-` is deliberate and is a
# guard against a near miss that has not happened YET: the constant's line is 2 kB
# of version history, so any hunk that reaches line 116 carries the whole thing as
# CONTEXT, and a reader keyed on the text alone would call that PR compliant.
# Measured on the committed fixtures: neither #693's nor #696's generator patch
# mentions the constant at all -- their hunks start at line 58 and never reach it --
# so the context trap is not what caught those two. It is one line of cheap
# insurance, not a reconstruction of the incident; do not read it as the latter.
ADDED_VERSION = re.compile(r"^\+%s\s*=\s*(\d+)" % VERSION_CONST, re.M)
REMOVED_VERSION = re.compile(r"^-%s\s*=\s*(\d+)" % VERSION_CONST, re.M)

# A heading LINE that opens a schema-decision section must carry BOTH words. Same
# construction, and the same reason, as the audit gate's: a declaration is read
# only off a qualifying heading or the section one opens, never out of loose body
# prose, because prose matches wander onto unrelated sentences and a gate that
# half-reads a body is worse than one that says plainly which half was missing.
SCHEMA_HEADING = re.compile(
    r"^(#{1,6})\s*(.*\bschema\b.*)$", re.M | re.I)
HEADING_QUALIFIER = re.compile(r"\bversion\b|\bbump\b", re.I)
ANY_HEADING = re.compile(r"^(#{1,6})\s+\S", re.M)

# What counts as "values do not change". Deliberately generous on wording and
# strict on placement: the author's sentence is read only inside a qualifying
# section, so breadth here costs nothing and a near miss on phrasing is the
# commonest way somebody believes they complied.
DECLARES_UNCHANGED = re.compile(
    r"(?:"
    r"values?\s+(?:are\s+|is\s+)?unchanged"
    r"|unchanged\s+values?"
    r"|no\s+(?:stored\s+|report\s+|analytics\s+|published\s+)?values?\s+(?:change|move|differ)"
    r"|(?:output|outputs|payload|report|reports)\s+(?:are\s+|is\s+)?(?:byte-)?identical"
    r"|(?:no|not)\s+\w{0,12}\s*(?:schema\s+)?bump\s+(?:is\s+)?(?:owed|needed|required)"
    r"|no\s+(?:schema\s+)?bump\b"
    r"|bit-for-bit|byte-identical"
    r"|values?\s+do\s+not\s+change"
    r"|does\s+not\s+change\s+(?:any\s+)?values?"
    r")",
    re.I,
)


class PathError(RuntimeError):
    """The output path could not be derived. Never degrade this into an empty set:
    an empty path means every PR is out of scope, which is the clean-zero shape."""


def _module_imports(src: str) -> set[str]:
    """`scripts.*` modules imported by one source file, from the AST rather than a
    regex -- `from scripts.roster_teams import (\\n a,\\n b,\\n)` is the repo's
    normal spelling and a line-oriented reader mishandles it."""
    out: set[str] = set()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == "scripts" or node.module.startswith("scripts."):
                if node.module != "scripts":
                    out.add(node.module.split(".", 1)[1])
                # `from scripts import x, y` names the modules in the alias list.
                else:
                    for alias in node.names:
                        out.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("scripts."):
                    out.add(alias.name.split(".", 1)[1])
    return out


def generator_closure(root: str) -> set[str]:
    """Repo-relative paths of the generator and every `scripts/` module it reaches.

    Imports that do not resolve to a file are dropped rather than raising: the
    closure must not stop existing because an unrelated import moved."""
    start = os.path.join(root, GENERATOR)
    if not os.path.isfile(start):
        raise PathError(
            f"{GENERATOR} is not in this checkout, so the analytics output path "
            f"could not be derived from its imports")
    seen: set[str] = set()
    queue = ["match_analytics"]
    while queue:
        mod = queue.pop()
        if mod in seen:
            continue
        path = os.path.join(root, "scripts", *mod.split(".")) + ".py"
        if not os.path.isfile(path):
            continue
        seen.add(mod)
        try:
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
        except OSError as exc:
            raise PathError(f"could not read {path}: {exc}")
        try:
            deps = _module_imports(src)
        except SyntaxError as exc:
            raise PathError(f"could not parse {path}: {exc}")
        queue.extend(d for d in deps if d not in seen)
    if len(seen) < 2:
        raise PathError(
            f"the import closure rooted at {GENERATOR} came back with {len(seen)} "
            f"module(s). A closure that is only its own root means the imports were "
            f"not read, and an under-derived path silently passes everything")
    return {"scripts/%s.py" % m.replace(".", "/") for m in seen}


def data_inputs(root: str, modules: set[str]) -> set[str]:
    """`config/` data files the closure reads, as named in its own source.

    Existence on disk is the filter. Comments and docstrings in these modules name
    paths that have since moved (`config/dod_classes.toml` for what is now
    `config/analytics/dod_classes.toml`), and a non-existent path can never be in a
    diff anyway -- so dropping it costs nothing and keeps the printed path honest."""
    found: set[str] = set()
    for rel in sorted(modules):
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as fh:
                src = fh.read()
        except OSError:
            continue
        for m in DATA_DIRECT.finditer(src):
            found.add(m.group(0))
        for m in DATA_JOINED.finditer(src):
            found.add("config/" + m.group(1))
    return {p for p in found if os.path.isfile(os.path.join(root, p))}


def output_path(root: str) -> tuple[set[str], set[str]]:
    mods = generator_closure(root)
    return mods, data_inputs(root, mods)


def touched(files: list[dict], path: set[str]) -> list[str]:
    return sorted({f.get("filename") for f in files
                   if f.get("filename") in path and f.get("status") != "removed"})


def version_change(files: list[dict]) -> tuple[str, object]:
    """('bumped'|'absent'|'suppressed'|'lowered', detail).

    `suppressed` is its own answer because GitHub omits `patch` on a very large or
    binary file, and a missing patch on the generator means this reader cannot see
    whether the constant moved. Reporting that as `absent` would fail an author who
    did the right thing; reporting it as a pass would certify what was not read."""
    for f in files:
        if f.get("filename") != GENERATOR:
            continue
        patch = f.get("patch")
        if patch is None:
            if f.get("status") == "removed":
                return "absent", None
            return "suppressed", None
        added = [int(m.group(1)) for m in ADDED_VERSION.finditer(patch)]
        removed = [int(m.group(1)) for m in REMOVED_VERSION.finditer(patch)]
        if not added:
            return "absent", None
        new = max(added)
        old = max(removed) if removed else None
        if old is not None and new <= old:
            return "lowered", (old, new)
        return "bumped", (old, new)
    return "absent", None


def schema_sections(body: str) -> list[tuple[str, str]]:
    """(heading line, section text) for each qualifying schema heading in a body.

    A section runs to the next heading of the same or higher level, so sub-headings
    an author writes underneath belong to it rather than terminating it."""
    body = (body or "").replace("\r\n", "\n")
    out = []
    for m in SCHEMA_HEADING.finditer(body):
        if not HEADING_QUALIFIER.search(m.group(2)):
            continue
        level = len(m.group(1))
        start, end = m.end(), len(body)
        for h in ANY_HEADING.finditer(body, start):
            if len(h.group(1)) <= level:
                end = h.start()
                break
        out.append((m.group(0).strip(), body[start:end]))
    return out


def classify(body: str) -> tuple[str, str | None]:
    """'declared-unchanged' (with the heading) or 'absent'."""
    sections = schema_sections(body)
    if not sections:
        return "absent", None
    for heading, section in sections:
        if DECLARES_UNCHANGED.search(heading) or DECLARES_UNCHANGED.search(section):
            return "declared-unchanged", heading
    return "absent", None


def body_headings(body: str) -> list[str]:
    body = (body or "").replace("\r\n", "\n")
    out = []
    for m in ANY_HEADING.finditer(body):
        nl = body.find("\n", m.start())
        out.append(body[m.start():nl if nl != -1 else len(body)].strip())
    return out


def near_miss_reason(body: str) -> str | None:
    """Why a body that reads as compliant was still classified `absent`.

    A declaration is only ever read off a qualifying heading, so a perfectly clear
    "no values change" under `## Notes` is never evaluated at all -- and nothing in
    the verdict would have said which half was missing. The audit gate learned this
    on its own #482; it is cheaper to inherit the lesson than to repeat it."""
    if schema_sections(body or ""):
        return None
    m = DECLARES_UNCHANGED.search(body or "")
    if not m:
        return None
    found = body_headings(body or "")
    shown = ", ".join(repr(h[:80]) for h in found) if found else "none at all"
    return (
        f"its body carries wording this gate would read as a declaration that values "
        f"do not change ({m.group(0).strip()[:80]!r}), but a declaration is only read "
        f"off a heading that OPENS a schema section and no heading here qualifies -- "
        f"so nothing read it. A qualifying heading line must carry `schema` AND "
        f"`version` or `bump`: `## Analytics schema version: values unchanged` "
        f"qualifies; `## Schema`, `## Notes` and `## Scope` do not. "
        f"Headings found: {shown}."
    )


def verdict(files: list[dict], body: str, modules: set[str], data: set[str]):
    """(answer, explanation, hit-list). Answers: 'out-of-path', 'bumped',
    'declared', 'suppressed', 'lowered', 'nothing'."""
    path = modules | data
    hits = touched(files, path)
    if not hits:
        return "out-of-path", "it changes no file in the analytics output path", []

    state, detail = version_change(files)
    if state == "suppressed":
        return ("suppressed",
                f"it changes {GENERATOR} and GitHub supplied no patch for it, so "
                f"whether {VERSION_CONST} moved could not be read", hits)
    if state == "lowered":
        old, new = detail
        return ("lowered",
                f"its diff moves {VERSION_CONST} from {old} to {new}. A non-increasing "
                f"version re-skips every report already at {old}, which is the exact "
                f"failure a bump exists to end", hits)
    if state == "bumped":
        old, new = detail
        was = f"from {old} " if old is not None else ""
        return ("bumped", f"its own diff moves {VERSION_CONST} {was}to {new}", hits)

    kind, heading = classify(body)
    if kind == "declared-unchanged":
        return ("declared",
                f"its body declares under {heading!r} that stored values do not change",
                hits)
    return "nothing", near_miss_reason(body), hits


# --------------------------------------------------------------------------- controls

_BUMP_PATCH = ("@@ -116,1 +116,1 @@\n"
               "-%s = 30  # history\n"
               "+%s = 31  # history; 31: a control\n" % (VERSION_CONST, VERSION_CONST))
_CONTEXT_PATCH = ("@@ -112,6 +112,7 @@\n"
                  " import sys\n"
                  "+import re\n"
                  " \n"
                  " %s = 30  # history\n" % VERSION_CONST)


def assert_discriminating(modules: set[str], data: set[str]) -> list[str]:
    """Drive the verdict BOTH ways on synthetic inputs, on every real run.

    A gate with one subject cannot be told apart from a gate that always passes by
    looking at its green, and the two failures that matter here are opposite: an
    always-pass reader reproduces #693 and #696 exactly, and an always-fail reader
    gets switched off within a week. Each is refuted here rather than only in the
    unit tests, because the unit tests do not run in this workflow.

    The two near misses are the ones authors actually write: the generator edited
    around the constant, with the constant sitting in the hunk's CONTEXT lines rather
    than in an added one, and a correct sentence under a heading that does not
    qualify."""
    sample = sorted(modules)[0]
    problems: list[str] = []
    cases = [
        ("a docs-only diff", [{"filename": "docs/X.md", "status": "modified",
                               "patch": "@@ -1 +1 @@\n-a\n+b\n"}], "", "out-of-path"),
        ("a test-only diff", [{"filename": "tests/unit/test_x.py", "status": "modified",
                               "patch": "@@ -1 +1 @@\n-a\n+b\n"}], "", "out-of-path"),
        ("an analytics module changed with no bump and an empty body",
         [{"filename": sample, "status": "modified",
           "patch": "@@ -1 +1 @@\n-a\n+b\n"}], "", "nothing"),
        ("the generator edited near the constant, constant only in context",
         [{"filename": GENERATOR, "status": "modified", "patch": _CONTEXT_PATCH}],
         "## Scope\n\nValues only.\n", "nothing"),
        ("a real bump in the generator's own diff",
         [{"filename": GENERATOR, "status": "modified", "patch": _BUMP_PATCH}],
         "", "bumped"),
        ("a declaration under a qualifying heading",
         [{"filename": sample, "status": "modified",
           "patch": "@@ -1 +1 @@\n-a\n+b\n"}],
         "## Analytics schema version\n\nA pure rename: stored values are unchanged.\n",
         "declared"),
        ("the same sentence under a heading that does not qualify",
         [{"filename": sample, "status": "modified",
           "patch": "@@ -1 +1 @@\n-a\n+b\n"}],
         "## Notes\n\nA pure rename: stored values are unchanged.\n", "nothing"),
        ("a suppressed patch on the generator",
         [{"filename": GENERATOR, "status": "modified", "patch": None}],
         "", "suppressed"),
        ("a version moved backwards",
         [{"filename": GENERATOR, "status": "modified",
           "patch": "@@ -116 +116 @@\n-%s = 30\n+%s = 29\n" % (VERSION_CONST,
                                                               VERSION_CONST)}],
         "", "lowered"),
    ]
    for label, files, body, want in cases:
        got = verdict(files, body, modules, data)[0]
        if got != want:
            problems.append(
                f"control failed: given {label} this check answered {got!r} and not "
                f"{want!r} -- it is not reading its subject")
    if data:
        got = verdict([{"filename": sorted(data)[0], "status": "modified",
                        "patch": "@@ -1 +1 @@\n-1\n+2\n"}], "", modules, data)[0]
        if got != "nothing":
            problems.append(
                f"control failed: a change to the data input {sorted(data)[0]} with no "
                f"bump answered {got!r} and not 'nothing' -- the data leg is not wired")
    return problems


# ------------------------------------------------------------------------------- io

def resolve_repo(explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("GITHUB_REPOSITORY")
    if env:
        return env
    raise RuntimeError(
        "no --repo and no GITHUB_REPOSITORY, so there is nothing to read the pull "
        "request from")


def _api(url: str):
    import urllib.error
    import urllib.request
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError(
            "no GITHUB_TOKEN/GH_TOKEN, so this pull request could not be read. Being "
            "unable to look is not evidence that it recorded a decision.")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ktp-analytics-schema-decision",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                raise RuntimeError(f"GitHub returned HTTP {resp.status} for {url}")
            return json.loads(resp.read().decode("utf-8")), resp.headers
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub returned HTTP {exc.code} for {url}: {exc.reason}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not reach the GitHub API: {exc.reason}")


def fetch_body(repo: str, number: int) -> str:
    """Read now, from the API, rather than from `github.event.pull_request.body`.

    The event payload is frozen at trigger time, so a declaration added afterwards
    would need a re-run -- and a re-run replays the stale payload, which is how the
    coordination gate's re-run trap works. Reading live makes `gh run rerun` sound
    here; the `edited` trigger is still what gets the fix re-read without one."""
    pr, _ = _api(f"https://api.github.com/repos/{repo}/pulls/{number}")
    return pr.get("body") or ""


def fetch_files(repo: str, number: int) -> list[dict]:
    """Every changed file, paginated. A truncated list is a silent pass: the
    analytics module could be on page 2."""
    out: list[dict] = []
    page = 1
    while True:
        batch, _ = _api(
            f"https://api.github.com/repos/{repo}/pulls/{number}/files"
            f"?per_page=100&page={page}")
        if not isinstance(batch, list):
            raise RuntimeError("the pull-request files endpoint did not return a list")
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1
        if page > 30:
            raise RuntimeError(
                "more than 3000 changed files; refusing to judge a list this reader "
                "may have truncated")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pr", default=os.environ.get("PR_NUMBER"))
    ap.add_argument("--repo", default=None)
    ap.add_argument("--root", default=".")
    ap.add_argument("--body-file", default=None)
    ap.add_argument("--files-json", default=None)
    ap.add_argument("--print-path", action="store_true",
                    help="print the derived output path and exit 0")
    args = ap.parse_args()

    try:
        modules, data = output_path(args.root)
    except PathError as exc:
        print(f"::error::{exc}")
        print("::error::refusing to certify -- a path this reader could not derive "
              "would put every pull request out of scope")
        return 2

    print(f"analytics output path, derived from {args.root}: {len(modules)} module(s) in "
          f"the import closure rooted at {GENERATOR}, {len(data)} config data input(s).")
    if args.print_path:
        for p in sorted(modules):
            print(f"  module  {p}")
        for p in sorted(data):
            print(f"  data    {p}")
        return 0
    print(f"  data inputs: {', '.join(sorted(data)) or 'none'}")

    problems = assert_discriminating(modules, data)
    if problems:
        for p in problems:
            print(f"::error::{p}")
        print("::error::refusing to certify -- this check did not prove it discriminates")
        return 2
    print("controls: docs-only and test-only diffs are out of scope; an analytics "
          "module changed with no bump fails; the generator edited near the constant "
          "with it only in context fails; a real bump passes; a declaration under a "
          "qualifying heading passes; the same sentence without one fails; a suppressed "
          "patch and a lowered version both refuse.")

    number = None
    if args.pr not in (None, ""):
        try:
            number = int(str(args.pr).lstrip("#"))
        except ValueError:
            print(f"::error::--pr {args.pr!r} is not a pull request number")
            return 2
    if number is None and not (args.files_json and args.body_file):
        print("::error::no pull request to judge: pass --pr, set PR_NUMBER, or supply "
              "both --files-json and --body-file. A run with no subject has measured "
              "nothing.")
        return 2

    try:
        if args.files_json:
            with open(args.files_json, encoding="utf-8") as fh:
                files = json.load(fh)
            source = args.files_json
        else:
            repo = resolve_repo(args.repo)
            files = fetch_files(repo, number)
            source = f"{repo} (GitHub API)"
        if args.body_file:
            with open(args.body_file, encoding="utf-8") as fh:
                body = fh.read()
        else:
            body = fetch_body(resolve_repo(args.repo), number)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"::error::{exc}")
        print("::error::refusing to certify -- a check that could not read its own pull "
              "request has measured nothing")
        return 2

    label = f"PR #{number}" if number is not None else "this change"
    print(f"subject: {label} from {source}, {len(files)} changed file(s)")

    answer, why, hits = verdict(files, body, modules, data)
    if hits:
        print(f"in the analytics output path: {', '.join(hits)}")

    if answer in ("out-of-path", "bumped", "declared"):
        print(f"\nanalytics schema decision: OK -- {why}.")
        print("⚠️ This is a record that a DECISION was made, and nothing more. It is "
              "not evidence the numbers are right: a bump costs one character, the "
              "author need not have regenerated anything, and the regeneration is an "
              "operator act on another host. Correctness still belongs to the tests "
              "and to the person reading the diff.")
        return 0

    if answer == "suppressed":
        print(f"::error::{label} {why}. Refusing to certify.")
        return 2

    if answer == "lowered":
        print(f"::error::{label} {why}.")
        return 1

    print(f"::error::{label} changes the analytics output path and records no decision "
          f"about {VERSION_CONST}. Either ONE of two routes clears it: (1) bump "
          f"{VERSION_CONST} in {GENERATOR} in THIS pull request's own diff, appending a "
          f"clause to its history comment that says what changed; or (2) if stored "
          f"values genuinely do not move -- a rename, a comment, a test-only helper -- "
          f"say so in the body under a heading whose line carries `schema` AND "
          f"`version` or `bump`, for example `## Analytics schema version: values "
          f"unchanged`, with one sentence of why. Route 2 is read ONLY from such a "
          f"heading or the section it opens, so the same sentence in loose prose is "
          f"never read.")
    print(f"::error::Why this is not pedantry: {VERSION_CONST} is the generator's only "
          f"test for \"already current\", so a report already at the current number is "
          f"SKIPPED whichever code built it. On 2026-10-12 two merged PRs changed the "
          f"analytics and left it alone, and 237 published reports kept pre-fix values "
          f"with nothing that would ever revisit them. Full CI was green on both.")
    if why:
        print(f"::error::{label}: {why}")
    return 1


def cli() -> int:
    """main(), with anything unforeseen mapped to 2 rather than escaping as 1.

    Exit 1 means "the controls passed, here is the finding"; an uncaught exception
    also leaves the interpreter on 1, so a crash would arrive wearing a verdict over
    however much output had already been flushed. `except Exception` is deliberate
    and must not be widened -- KeyboardInterrupt still aborts rather than reading as
    a refusal."""
    try:
        return main()
    except Exception:
        traceback.print_exc()
        print("::error::EXIT 2 -- this run did not finish, so anything above it is "
              "partial. Not being able to check is not a clean result.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(cli())
