#!/usr/bin/env python3
"""Refuse to touch the fleet from a checkout that is behind `origin/main`.

The trap this closes, in the order it happens:

  1. A local checkout falls behind. Nothing reports that; `git status` is not
     part of anyone's deploy ritual.
  2. Someone runs `python scripts/stage-wave.py ...` from it.
  3. The old copy parses its own arguments, connects to 24 hosts, stages the
     artifacts, verifies the md5s, and prints a clean 24/24.
  4. Everything the newer version would have done that the old one has never
     heard of simply does not happen -- and no flag was rejected, because the
     old copy has no such flag to reject. An unknown flag is a usage error; a
     flag that was never passed is silence.

The loss that costs something is `--pull-live`: it downloads each artifact's
LIVE counterpart before staging, and the fleet keeps no rollback copies. The
swap is `mv -f`, and these artifacts are not byte-reproducible (`.amxx` bakes a
per-minute build stamp, ReHLDS bakes `__DATE__`). The running build is the only
copy of itself that exists, and the stale stager walks past it without a word.
The wave ledger is the same shape of loss one layer up: the wave lands, the
ledger has no entry, and `ktp-wave-ledger.py reconcile` is blind to it forever.

It happened once already and was caught by hand on the 1.23.2 wave; the ledger
entry was written afterwards from memory. The standing remedy was a sentence in
a doc -- "run it out of `git show origin/main:` instead" -- which is a rule
applied from memory, and therefore a rule applied sometimes.

WHAT IT ASKS
------------
Not "is the repo current" -- one unrelated local edit would then block a deploy.
It asks, of the file that is actually executing and of the siblings that file
loads: does this differ from `origin/main`? That is `git diff` against the ref,
and git is asked to answer it rather than a hash being recomputed here: the
checkouts set `core.autocrlf=input` and carry a `.gitattributes`, so raw bytes
and the stored blob legitimately differ and a hand-rolled comparison reports
drift on files that are identical.

FAIL-CLOSED, AND WHERE THE EDGE IS
----------------------------------
Every answer that is not "identical to the ref" refuses: drift, no checkout, the
path missing from the ref, a git invocation that fails, a fetch that fails on a
copy that otherwise looks clean. "I could not tell" and "it is fine" must not
produce the same outcome, because the whole defect is a check that returned
silence.

Freshness of the ref itself is settled at run time, by fetching. The accepted
cost is a dependency on reaching the git remote while staging. That dependency
is strictly weaker than the one the operation already has -- staging opens SSH
to 24 hosts across five providers -- so a run that can stage can fetch. The
alternative, a hash recorded in the tree, is recorded in the same file that goes
stale, and a stale copy carries a stale expectation that agrees with itself.

If the fetch fails the comparison still runs against whatever `origin/main` is
already on disk, because a copy that differs from even a KNOWN-OLD ref is a
finding that needs no network to be true. Only the clean-but-unverifiable case
needs the operator (`KTP_FRESHNESS_OFFLINE`).

AN INSTALLED COPY
-----------------
A file in `/usr/local/bin` is in no checkout, and the cron entry that runs it
has no checkout to run it from. Refusing it as "no provenance" would turn the
nightly post-restart soak into an exit 3 every night. But it does have
provenance: `ktp-install` wrote a row for it in the deploy manifest, naming the
repo, the commit and the blob it was installed from. So for a file outside any
checkout the question is asked of that row, in two legs, and both must hold:

  1. its bytes still have the md5 of its LAST manifest row -- untouched since
     install. A hand-edit in place, or a copy nobody recorded, has no row it
     matches, and is refused the same way a file in a temp dir is.
  2. those bytes are the blob at the FETCHED ref for the row's source_path, in
     the checkout named by KTP_FRESHNESS_REPO (default /opt/ktp-infra). A row
     that is honest about an old commit is still an old copy, and is refused.

Leg 2 is the checkout rule again, compared by md5 rather than by `git diff`:
`ktp-install` writes the blob's exact bytes, so there is no line-ending
normalisation between them to get wrong. The fetch writes one remote-tracking
ref and nothing else, because that checkout is never pulled.

INERT CONTEXTS
--------------
Under pytest and under GitHub Actions the check reports and returns. In CI the
provenance is the checked-out sha, which is recorded; in a test the harness is
not a deploy, and the suite must be able to exercise a `main()` on a branch that
is by definition not `origin/main` yet -- including the branch that changes this
file. Both are named in the output, never silent.

This guards against ACCIDENT, not evasion. Anything here is trivially bypassed
by someone who wants to; the failure it exists for is forgetting that a checkout
got old, which nothing else on this estate reports.

Env:
  KTP_FRESHNESS_REF       ref to compare against (default: origin/main)
  KTP_FRESHNESS_REPO      checkout to verify against, for a copy extracted to a
                          temp path outside any tree; for an installed copy, the
                          checkout its manifest row is resolved in
                          (default: /opt/ktp-infra)
  KTP_MANIFEST            deploy manifest to read (default: the system and user
                          manifests ktp-install writes)
  KTP_FRESHNESS_OFFLINE   non-empty reason; accepts an unfetchable ref that the
                          local comparison found clean. Never skips the compare.
  KTP_FRESHNESS_BYPASS    non-empty reason; proceeds after a refusal, printing
                          the full drift report and the reason. Exists because
                          the alternative to a recorded override is an
                          unrecorded one -- copying the file somewhere the guard
                          cannot reach costs about as much and leaves no trace.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys

DEFAULT_REF = "origin/main"
DEFAULT_INSTALLED_REPO = "/opt/ktp-infra"
# Where and how ktp-install records; a path's current state is its LAST row.
SYSTEM_MANIFEST = "/usr/local/share/ktp-infra/DEPLOYED.tsv"
USER_MANIFEST = os.path.expanduser("~/.ktp/DEPLOYED.tsv")
MANIFEST_HEADER = ["installed_path", "md5", "source_repo", "source_commit",
                   "source_path", "deployed_at_iso", "previous_md5", "deployed_by"]
_FETCH_TIMEOUT = 45
_GIT_TIMEOUT = 60
# How far back through a path's history to look for the running copy. Bounded so
# a pathological history cannot turn the guard into the slow part of a deploy;
# not finding it inside the window is reported as not-found, never as found.
_HISTORY_WINDOW = 400


class FreshnessError(RuntimeError):
    """Raised when the running file is not provably the current one."""


def _git(repo, *args, timeout=_GIT_TIMEOUT, raw=False):
    """Run git, returning (rc, stdout, stderr). Never raises on a non-zero rc.

    `raw` keeps stdout exactly as git produced it. File contents must be read
    that way: stripping costs the trailing newline, which understates every
    line count taken off the ref by one and quietly mangles a file that opens
    with a blank line.
    """
    try:
        p = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode, (p.stdout if raw else p.stdout.strip()), p.stderr.strip()
    except FileNotFoundError:
        return 127, "", "git not found on PATH"
    except subprocess.TimeoutExpired:
        return 124, "", f"git {' '.join(args)} timed out after {timeout}s"


def _toplevel(start_dir):
    rc, out, _ = _git(start_dir, "rev-parse", "--show-toplevel")
    return out if rc == 0 and out else None


def _long_options(text):
    """Long options a file mentions. Deliberately over-broad -- it reads
    docstrings and help text too, because a name that appears only in the usage
    block still tells the reader what the newer copy knows about, which is the
    question being answered. `--help` is dropped: argparse gives it to every
    script, so its presence or absence carries nothing."""
    return set(re.findall(r"--[a-z][a-z0-9]*(?:-[a-z0-9]+)*", text)) - {"--help"}


def _top_level_names(text):
    return set(re.findall(r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M))


def _blob(repo, ref, rel):
    rc, out, _ = _git(repo, "show", f"{ref}:{rel}", raw=True)
    return out if rc == 0 else None


def _matching_commit(repo, ref, rel):
    """The most recent commit on `ref` whose version of `rel` is what is on disk.

    Returns (sha, commits_since) or (None, None). `None` means the running copy
    is not any recorded version of this path -- a hand-edit, a partial merge, or
    a file from another branch -- which is a different and worse finding than
    being behind by a known number of commits, and is reported as such.
    """
    rc, out, _ = _git(repo, "log", f"--max-count={_HISTORY_WINDOW}",
                      "--format=%H", ref, "--", rel)
    if rc != 0 or not out:
        return None, None
    for depth, sha in enumerate(out.splitlines()):
        if _git(repo, "diff", "--quiet", sha, "--", rel)[0] == 0:
            return sha, depth
    return None, None


def _describe_drift(repo, ref, rel):
    """What the reader would have lost. Every number here is computed."""
    lines = []
    disk_path = os.path.join(repo, rel)
    try:
        with open(disk_path, "r", encoding="utf-8", errors="replace") as fh:
            running = fh.read()
    except OSError as exc:
        running = ""
        lines.append(f"    (could not read {disk_path}: {exc})")
    current = _blob(repo, ref, rel) or ""

    missing_opts = sorted(_long_options(current) - _long_options(running))
    if missing_opts:
        lines.append("    flags on %s that this copy does not have:" % ref)
        lines.append("      " + "  ".join(missing_opts))

    missing_names = sorted(_top_level_names(current) - _top_level_names(running))
    if missing_names:
        lines.append("    functions/classes on %s that this copy does not have:" % ref)
        lines.append("      " + "  ".join(missing_names))

    gained_opts = sorted(_long_options(running) - _long_options(current))
    if gained_opts:
        lines.append("    present here and NOT on %s (local or unmerged work):" % ref)
        lines.append("      " + "  ".join(gained_opts))

    running_lines = running.count("\n")
    current_lines = current.count("\n")
    lines.append(f"    size: {running_lines} lines here, {current_lines} on {ref}")

    sha, since = _matching_commit(repo, ref, rel)
    if sha is None:
        lines.append(f"    this copy matches NO commit of {rel} in the last "
                     f"{_HISTORY_WINDOW} touching {ref} -- it is not merely old, "
                     f"it is a version that was never on the ref")
    else:
        lines.append(f"    this copy is {sha[:12]}, {since} commit(s) behind "
                     f"{ref} on this path:")
        rc, out, _ = _git(repo, "log", "--format=      %h %s", f"{sha}..{ref}", "--", rel)
        if rc == 0 and out:
            lines.extend(out.splitlines())

    rc, out, _ = _git(repo, "rev-list", "--count", f"HEAD..{ref}")
    if rc == 0 and out:
        lines.append(f"    (whole checkout is {out} commit(s) behind {ref})")

    return lines


def _manifest_row(path):
    """Return ((manifest, last row for `path`) or None, error or None)."""
    if os.environ.get("KTP_MANIFEST"):
        manifests = [os.environ["KTP_MANIFEST"]]
    else:
        manifests = [SYSTEM_MANIFEST, USER_MANIFEST]
    names = {os.path.abspath(path), os.path.realpath(path)}
    found = None
    for manifest in manifests:
        if not os.path.exists(manifest):
            continue
        try:
            with open(manifest, encoding="utf-8") as fh:
                lines = fh.read().split("\n")
        except OSError as exc:
            return None, f"cannot read deploy manifest {manifest}: {exc}"
        if lines and lines[-1] == "":
            lines.pop()
        if not lines or lines[0].split("\t") != MANIFEST_HEADER:
            return None, f"deploy manifest {manifest} has a missing or unexpected header"
        for n, line in enumerate(lines[1:], start=2):
            cols = line.split("\t")
            if len(cols) != len(MANIFEST_HEADER):
                return None, f"deploy manifest {manifest}:{n} does not parse"
            row = dict(zip(MANIFEST_HEADER, cols))
            if row["installed_path"] in names:
                found = (manifest, row)
    return found, None


def _check_installed(script_path, ref, also):
    """Verify copies outside any checkout: manifest row first, then the fetched ref."""
    here = os.path.dirname(script_path)
    paths = [script_path, *(os.path.abspath(os.path.join(here, n)) for n in also)]
    rows = []
    for path in paths:
        found, err = _manifest_row(path)
        if err:
            return [f"Cannot verify {path}: {err}.\n  An unreadable manifest proves nothing."]
        if not found:
            return [
                f"Cannot verify {os.path.basename(path)} is current: it is not "
                f"inside a git checkout, and no deploy manifest records it.\n"
                f"  looked for: {path}\n"
                f"  A copy extracted to a temp path has no provenance and this guard "
                f"will not assume one.\n"
                f"  Run it from the checkout, or install it with ktp-install so the "
                f"manifest says which blob it is."
            ]
        manifest, row = found
        try:
            with open(path, "rb") as fh:
                have = hashlib.md5(fh.read()).hexdigest()
        except OSError as exc:
            return [f"Cannot verify {path}: {exc}."]
        if have != row["md5"]:
            return [
                f"{path} DIFFERS from its deploy-manifest row.\n"
                f"    on disk:  {have}\n"
                f"    recorded: {row['md5']} ({row['source_path']} at "
                f"{row['source_commit'][:12]}, {manifest})\n"
                f"    It was edited in place or copied without ktp-install; either "
                f"way nothing says which version it is."
            ]
        rows.append((path, have, row))

    repo = os.path.abspath(os.environ.get("KTP_FRESHNESS_REPO") or DEFAULT_INSTALLED_REPO)
    top = _toplevel(repo) if os.path.isdir(repo) else None
    if not top:
        return [f"Cannot verify installed copies against {ref}: {repo} is not a git "
                f"checkout. Point KTP_FRESHNESS_REPO at the one they were installed from."]
    rc, url, _ = _git(top, "remote", "get-url", "origin")
    url = url.replace("\\", "/").rstrip("/") if rc == 0 else ""
    name = url.split("/")[-1] if url else os.path.basename(top)
    name = name[:-4] if name.endswith(".git") else name

    remote, _, branch = ref.partition("/")
    # One remote-tracking ref and nothing else: that checkout is never pulled.
    fetch_rc, _, fetch_err = _git(
        top, "fetch", "--quiet", "--no-tags", "--refmap=", remote,
        f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}", timeout=_FETCH_TIMEOUT)

    problems = []
    for path, have, row in rows:
        if row["source_repo"].split("/")[-1] != name:
            problems.append(f"Cannot verify {path}: its manifest row names "
                            f"{row['source_repo']}, but {top} is {name}.")
            continue
        rel = row["source_path"]
        try:
            blob = subprocess.run(["git", "-C", top, "cat-file", "blob", f"{ref}:{rel}"],
                                  capture_output=True, timeout=_GIT_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            problems.append(f"Cannot verify {path}: {exc}.\n  Undetermined is not clean.")
            continue
        if blob.returncode != 0:
            problems.append(f"Cannot verify {path}: {rel} does not exist at {ref} in {top}.")
            continue
        if hashlib.md5(blob.stdout).hexdigest() == have:
            continue

        block = [f"{path} is STALE: installed from {rel} at "
                 f"{row['source_commit'][:12]}, and {ref} has moved past it."]
        with open(path, encoding="utf-8", errors="replace") as fh:
            running = fh.read()
        missing = sorted(_long_options(blob.stdout.decode("utf-8", "replace"))
                         - _long_options(running))
        if missing:
            block.append(f"    flags on {ref} that this copy does not have:")
            block.append("      " + "  ".join(missing))
        rc, out, _ = _git(top, "log", "--format=      %h %s",
                          f"{row['source_commit']}..{ref}", "--", rel)
        if rc == 0 and out:
            block.append(f"    commits on {ref} since the installed one, on this path:")
            block.extend(out.splitlines())
        block.append(f"    reinstall: ktp-install --repo {top} --commit <{ref} sha> "
                     f"--src {rel} --dest {path} --expect-md5 {have}")
        problems.append("\n".join(block))

    return problems or _fetch_verdict(fetch_rc, fetch_err, remote, branch, ref)


def _fetch_verdict(fetch_rc, fetch_err, remote, branch, ref):
    """Clean against a ref that could not be refreshed: refuse, unless declared offline."""
    if fetch_rc == 0:
        return []
    offline = os.environ.get("KTP_FRESHNESS_OFFLINE", "").strip()
    detail = (f"Could not fetch {remote} {branch}: "
              f"{fetch_err or f'git fetch exited {fetch_rc}'}")
    if not offline:
        return [
            f"{detail}\n"
            f"  The files match the {ref} already on disk, but nothing here "
            f"proves that ref is current, and a ref that has not moved since "
            f"the checkout went stale agrees with a stale copy.\n"
            f"  Fix the network, or set KTP_FRESHNESS_OFFLINE to a reason to "
            f"accept the on-disk ref."
        ]
    print(f"[freshness] ACCEPTING AN UNVERIFIED {ref}: {offline}", file=sys.stderr)
    print(f"[freshness]   {detail}", file=sys.stderr)
    return []


def _inert_context():
    if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
        return "pytest"
    if os.environ.get("GITHUB_ACTIONS"):
        return "github-actions"
    return None


def check(script_path, also=()):
    """Compare the running file (and `also`, its sibling loads) against the ref.

    Returns a list of human-readable problem blocks; empty means verified
    current. Raising is left to require_current() so a caller can ask without
    being exited.
    """
    ref = os.environ.get("KTP_FRESHNESS_REF") or DEFAULT_REF
    script_path = os.path.abspath(script_path)
    here = os.path.dirname(script_path)

    top = _toplevel(here)
    if not top:
        return _check_installed(script_path, ref, also)
    repo = os.path.abspath(os.environ.get("KTP_FRESHNESS_REPO") or top)

    targets = []
    for path in (script_path, *(os.path.join(here, name) for name in also)):
        path = os.path.abspath(path)
        try:
            rel = os.path.relpath(path, repo).replace(os.sep, "/")
        except ValueError:
            return [f"Cannot verify {path}: it is not under {repo}."]
        if rel.startswith(".."):
            return [f"Cannot verify {path}: it is not under {repo}."]
        targets.append(rel)

    remote, _, branch = ref.partition("/")
    fetch_rc, _, fetch_err = _git(repo, "fetch", "--quiet", remote, branch,
                                  timeout=_FETCH_TIMEOUT)

    problems = []
    for rel in targets:
        if _git(repo, "cat-file", "-e", f"{ref}:{rel}")[0] != 0:
            problems.append(
                f"Cannot verify {rel}: it does not exist at {ref}.\n"
                f"  Either {ref} is not fetched in this checkout, or this file is "
                f"not on the ref. Both mean its provenance is unknown, and a file "
                f"of unknown provenance does not get to write to the fleet."
            )
            continue

        rc, _, err = _git(repo, "diff", "--quiet", ref, "--", rel)
        if rc == 0:
            continue
        if rc != 1:
            problems.append(
                f"Cannot verify {rel}: `git diff` exited {rc}.\n"
                f"  {err or '(no stderr)'}\n"
                f"  Undetermined is not clean."
            )
            continue

        block = [f"{rel} DIFFERS from {ref}."]
        block.extend(_describe_drift(repo, ref, rel))
        block.append(f"    see the whole difference: "
                     f"git -C {repo} diff {ref} -- {rel}")
        problems.append("\n".join(block))

    if problems:
        # Drift against a ref that could not be refreshed is still drift. Say so
        # rather than muddying a real finding with a network caveat.
        return problems

    return _fetch_verdict(fetch_rc, fetch_err, remote, branch, ref)


def require_current(script_path, also=(), purpose=None):
    """Gate a fleet-writing entry point. Call it first thing in main().

    Place it AFTER parse_args so `--help` still answers without a network, and
    BEFORE any work -- including a dry run, because a dry run from a stale copy
    prints a plan that is wrong in exactly the way that is hard to notice.
    """
    name = os.path.basename(script_path)
    inert = _inert_context()
    if inert:
        print(f"[freshness] not gating ({inert}); provenance is the checked-out tree",
              file=sys.stderr)
        return

    problems = check(script_path, also=also)
    if not problems:
        return

    what = purpose or "write to the fleet"
    banner = [
        "",
        "=" * 78,
        f"REFUSING TO RUN {name}: it is not provably the current version.",
        "=" * 78,
    ]
    for block in problems:
        banner.append("")
        banner.append("  " + block.replace("\n", "\n  "))
    banner += [
        "",
        f"  This script can {what}. A version that is behind does not reject the",
        "  flags it lacks -- it never sees them, stages anyway, and reports success.",
        "",
        "  Refresh the checkout, then run it again.",
        "=" * 78,
        "",
    ]
    text = "\n".join(banner)

    bypass = os.environ.get("KTP_FRESHNESS_BYPASS", "").strip()
    if bypass:
        print(text, file=sys.stderr)
        print(f"[freshness] BYPASSED ON PURPOSE: {bypass}", file=sys.stderr)
        print("[freshness] Everything above is still true.", file=sys.stderr)
        return

    print(text, file=sys.stderr)
    raise SystemExit(3)


if __name__ == "__main__":
    # Reporting mode: name the drift for a path without running anything.
    import argparse

    ap = argparse.ArgumentParser(description="Report whether a script is current.")
    ap.add_argument("path", nargs="+", help="Script(s) to check.")
    args = ap.parse_args()
    bad = 0
    for p in args.path:
        found = check(p)
        if found:
            bad = 1
            for block in found:
                print(block, file=sys.stderr)
        else:
            print(f"{p}: current")
    raise SystemExit(bad)
