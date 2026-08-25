#!/usr/bin/env python3
"""ktp-lan-web-drift — does /opt/lan-web match sites/lan-web in the repo?

/opt/lan-web was hand-copied from June onward: no deploy script, no drift
check, 19 .deploy-bak-* directories as the fossil record. The cost was
concrete. On 2026-08-07 a file-level compare found the box running the PRE-fix
bracket.py -- the placement fix had been pushed to main on 08-02 and never
deployed -- while a 22-line warmup panel existed ONLY on the box and would
have been deleted by the first rsync from source.

Reports only; deploying is deploy-lan-web.sh's job. Three states matter and
they are NOT the same problem, so they are counted separately:

  differ    -- both sides have it, contents disagree (which side is right is
               a human call; that is why this does not auto-deploy)
  box-only  -- exists only on the server. A deploy with --delete DESTROYS it.
  repo-only -- committed but never deployed.

WHAT IT LOOKS AT, AND WHY THAT IS THE WHOLE POINT. This used to compare only
files whose name ended in one of seven suffixes. An allowlist answers "did the
files I expected change"; the question a --delete pre-flight has to answer is
"is there anything here I did not put here", and those are not the same
question. On 2026-08-16 the box held 29 .bak-* fossils that matched none of the
seven, so they were invisible: the check reported no box-only files and the
next --apply would have deleted all 29 with the guard reporting clean.

So: everything under the sync root is compared, and the only blind spot is
provision/lan-web-sync.exclude -- the same file rsync reads. An unknown file is
visible by default. Adding a blind spot means editing the exclude list, where
it is one line of review rather than a suffix nobody thinks about.

Line endings are normalised before comparing TEXT files. The box was copied
from Windows so its files carry CRLF; without normalising, every file reads as
drifted and the real signal is buried under 57 false positives. Files holding a
NUL byte are hashed raw -- rewriting bytes inside a PNG to decide whether two
PNGs match is how a real difference gets called a match.

WHICH SOURCE IT COMPARED. The repo side is a WORKING TREE, so the verdict is
about whichever branch is checked out and whatever is uncommitted in it. "In
sync" then reads as "in sync with main" when it may mean "in sync with
somebody's feature branch", and every future answer silently depends on who ran
it from where. So each report opens with a source: line naming the checkout and
whether sites/lan-web/app matches LAN_WEB_BASE_REF (default origin/main). It is
reported, not enforced -- refusing is deploy-lan-web.sh's job, and this stays a
reporter with a fixed exit-code contract.

Exit codes -- the deploy script branches on these, so they are an interface:
  0  in sync
  1  drift, but nothing box-only (safe to deploy: --delete destroys nothing)
  2  check failed (SSH/path/config error -- log it, do not alert; a transient
     failure must not flap, and must not be read as "clean")
  3  BOX-ONLY files present -- a deploy with --delete would destroy them
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import posixpath
import stat
import subprocess
import sys

# paramiko is imported in main(), not here: the exclude parsing and the local
# walk are what tests/unit exercises, and a hard import would make the module
# unimportable on a runner that has no SSH stack.

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTE_ROOT = os.environ.get("LAN_WEB_REMOTE", "/opt/lan-web/app")
EXCLUDE_FILE = os.path.join(REPO_ROOT, "provision", "lan-web-sync.exclude")
BASE_REF = os.environ.get("LAN_WEB_BASE_REF", "origin/main")

EXIT_SYNC, EXIT_DRIFT, EXIT_FAILED, EXIT_BOX_ONLY = 0, 1, 2, 3


class ExcludeError(Exception):
    pass


def load_excludes(path: str) -> tuple[list[str], list[str]]:
    """The exclude file as (directory globs, file globs).

    Refuses a pattern it cannot implement exactly. A silently-misparsed pattern
    would either hide files from the check or spuriously refuse a deploy, and
    only the first of those is loud.
    """
    dirs: list[str] = []
    files: list[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            pat = line.split("#", 1)[0].strip()
            if not pat:
                continue
            if pat.endswith("/"):
                pat = pat[:-1]
                target = dirs
            else:
                target = files
            if "/" in pat or not pat:
                raise ExcludeError(
                    "%s:%d: unsupported pattern %r -- only 'name/' and 'glob' "
                    "are implemented here" % (path, lineno, line.strip()))
            target.append(pat)
    if not dirs and not files:
        raise ExcludeError("%s: no patterns -- refusing to guess" % path)
    return dirs, files


def _excluded_dir(name: str, dir_globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, g) for g in dir_globs)


def _excluded_file(name: str, file_globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, g) for g in file_globs)


def _digest(data: bytes) -> str:
    # Binary is hashed as-is; only text gets its line endings normalised.
    if b"\x00" not in data:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _git(repo_root: str, *args: str):
    return subprocess.run(("git", "-C", repo_root) + args,
                          capture_output=True, text=True, timeout=30)


def source_provenance(repo_root: str, src_root: str, base_ref: str) -> str:
    """One line naming the checkout the repo side came from.

    UNKNOWN is a real answer and is said out loud: silently omitting the line
    would leave a report that looks like it was measured against base_ref.
    """
    rel = os.path.relpath(os.path.abspath(src_root), repo_root).replace(os.sep, "/")
    if rel.startswith(".."):
        return "source: %s -- OUTSIDE the repo, no ref to compare against" % src_root
    try:
        head = _git(repo_root, "rev-parse", "--short", "HEAD")
        name = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
        if head.returncode or name.returncode:
            return "source: %s -- provenance UNKNOWN (not a git checkout)" % rel
        at = "%s %s" % (name.stdout.strip(), head.stdout.strip())
        cmp_ = _git(repo_root, "diff", "--quiet", base_ref, "--", rel)
        if cmp_.returncode == 0:
            return "source: %s @ %s -- matches %s" % (rel, at, base_ref)
        if cmp_.returncode == 1:
            return ("source: %s @ %s -- DIFFERS from %s; this report is about "
                    "that tree, not %s" % (rel, at, base_ref, base_ref))
        return ("source: %s @ %s -- provenance UNKNOWN (%s not resolvable here)"
                % (rel, at, base_ref))
    except (OSError, subprocess.SubprocessError):
        return "source: %s -- provenance UNKNOWN (git unavailable)" % rel


def local_manifest(root: str, dir_globs, file_globs) -> dict[str, str]:
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _excluded_dir(d, dir_globs)]
        for fn in filenames:
            if _excluded_file(fn, file_globs):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if os.path.islink(path):
                out[rel] = "symlink:" + os.readlink(path).replace(os.sep, "/")
                continue
            with open(path, "rb") as fh:
                out[rel] = _digest(fh.read())
    return out


def remote_manifest(sftp, root: str, dir_globs, file_globs) -> dict[str, str]:
    out = {}
    stack = [root]
    while stack:
        cur = stack.pop()
        for entry in sftp.listdir_attr(cur):
            name = entry.filename
            full = posixpath.join(cur, name)
            mode = entry.st_mode or 0
            if stat.S_ISDIR(mode):
                if not _excluded_dir(name, dir_globs):
                    stack.append(full)
                continue
            if _excluded_file(name, file_globs):
                continue
            rel = posixpath.relpath(full, root)
            if stat.S_ISLNK(mode):
                out[rel] = "symlink:" + sftp.readlink(full)
                continue
            if not stat.S_ISREG(mode):
                # A fifo/socket/device is not something a deploy put here.
                # Record it rather than skipping, so it shows up as box-only.
                out[rel] = "special:%o" % stat.S_IFMT(mode)
                continue
            with sftp.open(full, "rb") as fh:
                out[rel] = _digest(fh.read())
    return out


def main() -> int:
    src_root = os.environ.get(
        "LAN_WEB_SRC",
        os.path.join(REPO_ROOT, "sites", "lan-web", "app"))
    if not os.path.isdir(src_root):
        print("source tree not found: %s" % src_root, file=sys.stderr)
        return EXIT_FAILED

    # Printed before the SSH work so it survives a check that fails there.
    print(source_provenance(REPO_ROOT, src_root, BASE_REF))

    try:
        dir_globs, file_globs = load_excludes(EXCLUDE_FILE)
    except (OSError, ExcludeError) as exc:
        print("exclude list unusable: %s" % exc, file=sys.stderr)
        return EXIT_FAILED

    try:
        import paramiko
    except ImportError:
        print("paramiko not available", file=sys.stderr)
        return EXIT_FAILED

    host = os.environ.get("DATA_SSH_HOST", "74.91.112.242")
    user = os.environ.get("DATA_SSH_USER", "root")
    key = os.environ.get("DATA_SSH_KEY", os.path.expanduser("~/.ssh/id_ed25519"))

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=user, key_filename=key, timeout=30,
                       allow_agent=False, look_for_keys=False)
        sftp = client.open_sftp()
        box = remote_manifest(sftp, REMOTE_ROOT, dir_globs, file_globs)
        sftp.close()
    except Exception as exc:                                  # noqa: BLE001
        print("check failed: %s" % exc, file=sys.stderr)
        return EXIT_FAILED
    finally:
        client.close()

    repo = local_manifest(src_root, dir_globs, file_globs)
    if not repo or not box:
        # an empty manifest compares "clean" against anything; refuse to say OK
        print("empty manifest (repo=%d box=%d) -- check the paths, not the result"
              % (len(repo), len(box)), file=sys.stderr)
        return EXIT_FAILED

    differ = sorted(f for f in set(repo) & set(box) if repo[f] != box[f])
    box_only = sorted(set(box) - set(repo))
    repo_only = sorted(set(repo) - set(box))

    print("lan-web: %d files repo / %d box" % (len(repo), len(box)))
    if not (differ or box_only or repo_only):
        print("in sync")
        return EXIT_SYNC

    if box_only:
        print("\nBOX-ONLY (%d) -- a deploy with --delete would DESTROY these:" % len(box_only))
        for f in box_only:
            print("   + %s" % f)
    if repo_only:
        print("\nREPO-ONLY (%d) -- committed, never deployed:" % len(repo_only))
        for f in repo_only:
            print("   - %s" % f)
    if differ:
        print("\nDIFFER (%d) -- contents disagree:" % len(differ))
        for f in differ:
            print("   ! %s" % f)
    return EXIT_BOX_ONLY if box_only else EXIT_DRIFT


if __name__ == "__main__":
    sys.exit(main())
