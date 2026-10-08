#!/usr/bin/env python3
"""Hold docs/LIVE_SCRIPT_INVENTORY.md to the repo it points at.

That inventory records, per live file on a production host, an md5 and the commit
whose blob equals it. Until this script existed nothing read it: `git grep -l
LIVE_SCRIPT_INVENTORY -- tests/ .github/ scripts/` returned zero against a
positive control of 130 `def main` hits in scripts/. An unvalidated inventory of
what is installed on a production box does not stay silent when it rots -- it
gets cited. On 2026-10-07 a changelog fragment in this repo cited the
`ktp-data-server-health.sh` row as the live revision, and a coordination-ledger
entry from 2026-09-21 says a different build was installed. Both are durable
records, both were written in good faith, and nothing could adjudicate them.

TWO CLAIMS PER ROW, AND ONLY ONE OF THEM IS CHECKABLE FROM A CHECKOUT.

  REPO CLAIM  "the bytes with md5 X are in this repo at <repo>:<path>@<commit>"
              -> fully decidable here, for rows sourced from THIS repo.
  LIVE CLAIM  "the file at <live path> on <host> has md5 X"
              -> never decidable here. It needs a read on the host.

This script asserts the repo claim and REFUSES TO IMPLY THE LIVE ONE. Every run
prints how many live claims it verified, and with no --live-md5 that number is
zero. A clean exit from this check means the inventory is internally consistent
and honestly flagged; it does NOT mean the hosts match it. Read the two outcomes
asymmetrically -- the same discipline as scripts/check-archive-lift.py in the
doc set, and for the same reason: a careful probe of one half feels exactly like
verification of both.

THE ROT LEG: SUPERSEDED.

A row is a dated measurement, so the repo moving on does not make it false -- it
makes it mute. The defect is that the doc gave a reader no way to tell a row
that still describes the repo tip from one the repo has long since passed, and
the reader cited the second kind as current state. So: when the source path has
changed in the repo since the pinned commit, the row must carry the literal
token SUPERSEDED. Checked in BOTH directions -- a missing marker fails, and so
does a marker on a row whose pin is still current. That second leg is what keeps
the marker from becoming a permanent silencer: re-pin a row and its stale marker
fails the check instead of hiding the next drift.

Red on this leg means a script that is installed on a host changed in the repo,
and nobody recorded whether the host got it. That is the gap
docs/DEPLOY_MANIFEST.md exists to close. Pass --warn-superseded to downgrade the
leg to advisory if it ever proves noisier than it is worth; do not delete it.

THE PROVENANCE LEG: UNVERIFIABLE-PIN.

A pin is only provenance if a cloner can reach it. Three of the rows name commits
that are NOT ancestors of main -- one sits on an unmerged feature branch, two are
reachable from no ref at all -- so nobody who clones this repo can check those
rows, however carefully. That is invisible on a workstation that happens to still
hold the dangling object, which is exactly how it survived: the first CI run of
this script was the first time anything asked.

So REACHABILITY, not object presence, is the test -- `merge-base --is-ancestor`
against the ref, which gives the same answer in a fresh clone as in a well-fetched
one. An unreachable pin must carry the token UNVERIFIABLE-PIN, in both directions
again. Those rows get no md5 and no supersession verdict, because a fresh clone
cannot compute one; where the object happens to be present, what it says is
printed as information and gates nothing.

A shallow clone makes every reachability answer unreliable, so it exits 2 up
front rather than reporting per-row results it cannot stand behind.

  python3 scripts/check-live-script-inventory.py
  python3 scripts/check-live-script-inventory.py --selftest
  python3 scripts/check-live-script-inventory.py --live-md5 live.md5   # on/from the box

To close the live half, on the data server or a game host:

  md5sum /usr/local/bin/ktp-* /opt/ktp-backup.sh ... > live.md5

and feed that file back in. Rows named in the manifest get their live claim
checked; rows absent from it stay counted as unverified.

Exit 0 = every repo claim verifies and every flagged row is marked
     1 = a repo claim is false, or a SUPERSEDED / UNVERIFIABLE-PIN marker is
         missing or stale
     2 = the check could not trust itself (doc missing or unparseable, no row
         survived parsing, no row was hard-verifiable, a candidate line the
         grammar did not accept, or the clone is shallow -- which is correct:
         it cannot answer reachability)
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile

THIS_REPO = "KTPInfrastructure"
MARKER = "SUPERSEDED"
PIN_MARKER = "UNVERIFIABLE-PIN"
DEFAULT_DOC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "LIVE_SCRIPT_INVENTORY.md",
)

# A row in one of the per-host tables. The note column is where a pipe row's
# marker lives; a bullet row carries it at end of line.
_PIPE_ROW = re.compile(r"^\|(?P<cells>.*)\|\s*$")
_PIPE_RULE = re.compile(r"^\|[\s:|-]+\|\s*$")
_BULLET_ROW = re.compile(
    r"^-\s+`(?P<live>/[^`]+)`\s+`(?P<md5>[0-9a-f]{6,32})`\s*=\s*"
    r"`(?P<repo>[^`:]+):(?P<path>[^`]+)`\s*@\s*`(?P<commit>[0-9a-f]{6,40})`"
    r"(?P<tail>.*)$"
)
# A line that LOOKS like a bullet row but did not parse is a grammar hole, not a
# line to skip -- a silent skip here is the whole defect class this guards.
_BULLET_CANDIDATE = re.compile(r"^-\s+`/[^`]+`\s+`[0-9a-f]{6,}`")
_SOURCE = re.compile(
    r"^`(?P<repo>[^`:]+):(?P<path>[^`]+)`(?:\s*@\s*`(?P<commit>[0-9a-f]{6,40})`)?$"
)
_HEADER_CELLS = ("path", "md5", "verdict", "source", "note")

# md5 equality is asserted only where the row claims the live bytes ARE a blob.
# TEMPLATED means a filled .example, so its md5 provably differs from the
# template and asserting equality there would fail on correct rows.
HASHED_VERDICTS = frozenset({"MATCH"})
PINNED_VERDICTS = frozenset({"MATCH", "TEMPLATED"})
NO_SOURCE_VERDICTS = frozenset({"EXTERNAL", "THIRD-PARTY"})


class Row(object):
    def __init__(self, lineno, shape, live, md5, verdict, repo, path, commit, text):
        self.lineno = lineno
        self.shape = shape
        self.live = live
        self.md5 = md5
        self.verdict = verdict
        self.repo = repo
        self.path = path
        self.commit = commit
        self.marked = MARKER in text
        self.pin_marked = PIN_MARKER in text

    def __str__(self):
        where = "%s:%s" % (self.repo, self.path) if self.path else "--"
        pin = "@%s" % self.commit if self.commit else ""
        return "L%-5d %-10s %-11s %s%s" % (
            self.lineno, self.verdict, self.md5 or "--", where, pin)


class Git(object):
    """Every git call goes through here so a failure is never read as a zero."""

    def __init__(self, cwd):
        self.cwd = cwd

    def _run(self, args):
        return subprocess.run(
            ["git"] + args, cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def resolve(self, rev):
        p = self._run(["rev-parse", "--verify", "%s^{commit}" % rev])
        return p.stdout.decode("ascii", "replace").strip() if p.returncode == 0 else None

    def blob(self, rev, path):
        """Bytes of <rev>:<path>, or None if the path is not there."""
        p = self._run(["cat-file", "blob", "%s:%s" % (rev, path)])
        return p.stdout if p.returncode == 0 else None

    def last_touch(self, rev, path):
        p = self._run(["log", "--format=%H", "-1", rev, "--", path])
        out = p.stdout.decode("ascii", "replace").strip()
        return out or None

    def is_shallow(self):
        p = self._run(["rev-parse", "--is-shallow-repository"])
        return p.stdout.decode("ascii", "replace").strip() == "true"

    def reachable(self, commit, ref):
        """Is <commit> an ancestor of <ref>? The only portable provenance test --
        object presence differs between a fresh clone and a long-lived one."""
        return self._run(["merge-base", "--is-ancestor", commit, ref]).returncode == 0


def parse(text):
    """(rows, structural_problems). A candidate line that does not parse is a problem."""
    rows, problems, in_table = [], [], False
    for lineno, raw in enumerate(text.split("\n"), 1):
        line = raw.strip()

        m = _BULLET_ROW.match(line)
        if m:
            rows.append(Row(lineno, "bullet", m.group("live"), m.group("md5"), "MATCH",
                            m.group("repo"), m.group("path"), m.group("commit"),
                            m.group("tail")))
            continue
        if _BULLET_CANDIDATE.match(line):
            problems.append("L%d: looks like an inventory bullet but the grammar "
                            "rejected it: %s" % (lineno, line))
            continue

        pm = _PIPE_ROW.match(line)
        if not pm:
            continue
        cells = [c.strip() for c in pm.group("cells").split("|")]
        lowered = [c.strip("* ").lower() for c in cells]
        if all(h in lowered for h in _HEADER_CELLS):
            in_table = True
            continue
        if _PIPE_RULE.match(line):
            continue
        if not in_table or len(cells) < 4:
            continue

        live, md5, verdict, source = cells[0], cells[1], cells[2].upper(), cells[3]
        note = cells[4] if len(cells) > 4 else ""
        if not live.startswith("`/"):
            continue
        live = live.strip("`")
        md5 = md5.strip("`")
        if verdict in NO_SOURCE_VERDICTS or not source.startswith("`"):
            rows.append(Row(lineno, "pipe", live, md5, verdict, None, None, None,
                            note))
            continue
        sm = _SOURCE.match(source)
        if not sm:
            problems.append("L%d: source cell is neither a backticked repo:path "
                            "nor an em-dash: %s" % (lineno, source))
            continue
        rows.append(Row(lineno, "pipe", live, md5, verdict, sm.group("repo"),
                        sm.group("path"), sm.group("commit"), note))
    return rows, problems


def read_md5_manifest(path):
    """md5sum output -> {live path: md5}."""
    out = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{32}", parts[0]):
                continue
            out[parts[1].lstrip("*").strip()] = parts[0]
    return out


def check(doc_path, repo_dir, ref, live_md5=None, warn_superseded=False, out=sys.stdout):
    def say(fmt, *a):
        out.write((fmt % a if a else fmt) + "\n")

    if not os.path.exists(doc_path):
        say("UNTRUSTWORTHY: inventory not found at %s", doc_path)
        return 2
    with open(doc_path, "r", encoding="utf-8") as fh:
        text = fh.read()

    git = Git(repo_dir)
    head = git.resolve(ref)
    if head is None:
        say("UNTRUSTWORTHY: cannot resolve ref %r in %s", ref, repo_dir)
        return 2
    if git.is_shallow():
        say("UNTRUSTWORTHY: %s is a shallow clone, so no pin's reachability can be "
            "answered. Fetch full history (actions/checkout fetch-depth: 0).", repo_dir)
        return 2

    rows, problems = parse(text)
    if not rows:
        say("UNTRUSTWORTHY: no inventory row parsed out of %s -- the grammar and the "
            "doc have diverged, or the tables are gone.", doc_path)
        return 2

    findings, marker_findings, pin_findings, hard_verified = [], [], [], 0
    classes = {"repo-pinned": [], "unreachable-pin": [], "repo-unpinned": [],
               "other-repo": [], "no-source": []}
    superseded, marked_ok, unreachable_notes = [], [], []

    for row in rows:
        if row.repo is None:
            classes["no-source"].append(row)
            continue
        if row.repo != THIS_REPO:
            classes["other-repo"].append(row)
            continue
        if not row.commit:
            classes["repo-unpinned"].append(row)
            # Still assertable: the named source must exist at the ref.
            if git.blob(head, row.path) is None:
                findings.append("%s -- source path is not in the repo at %s"
                                % (row, ref))
            else:
                hard_verified += 1
            continue

        if not git.reachable(row.commit, ref):
            # No fresh clone can read this row's blob, so neither the md5 nor the
            # supersession verdict is computable. The marker is the whole leg.
            classes["unreachable-pin"].append(row)
            if not row.pin_marked:
                pin_findings.append(
                    "%s -- pinned commit is not an ancestor of %s, so nobody who "
                    "clones can check this row; add the %s token, or re-pin it after "
                    "a read on the host" % (row, ref, PIN_MARKER))
            local = git.blob(row.commit, row.path)
            if local is not None:
                current = git.blob(head, row.path)
                same = current is not None and \
                    hashlib.md5(current).hexdigest() == hashlib.md5(local).hexdigest()
                unreachable_notes.append(
                    "  %s -- this clone happens to hold the object; its bytes %s "
                    "today's %s. Gates nothing: a fresh clone sees neither."
                    % (row.live, "equal" if same else "differ from", ref))
            continue
        if row.pin_marked:
            pin_findings.append(
                "%s -- carries %s but its pin IS reachable from %s; remove the token"
                % (row, PIN_MARKER, ref))

        classes["repo-pinned"].append(row)
        pinned = git.blob(row.commit, row.path)
        if pinned is None:
            findings.append("%s -- path is not present at its own pinned commit"
                            % row)
            continue
        pinned_md5 = hashlib.md5(pinned).hexdigest()
        if row.verdict in HASHED_VERDICTS and not pinned_md5.startswith(row.md5):
            findings.append("%s -- recorded md5 does not match the pinned blob (%s)"
                            % (row, pinned_md5[:len(row.md5)]))
            continue
        hard_verified += 1

        current = git.blob(head, row.path)
        if current is None:
            findings.append("%s -- source path has been removed from the repo at %s"
                            % (row, ref))
            continue
        overtaken = hashlib.md5(current).hexdigest() != pinned_md5
        if overtaken and not row.marked:
            tip = git.last_touch(head, row.path) or "?"
            marker_findings.append(
                "%s -- repo source changed since the pin (now %s); add the %s token "
                "to this row, or re-pin it after a read on the host"
                % (row, tip[:10], MARKER))
        elif row.marked and not overtaken:
            marker_findings.append(
                "%s -- carries %s but its pin IS the current repo content; remove "
                "the token" % (row, MARKER))
        elif overtaken:
            superseded.append(row)
            marked_ok.append(row)

    live_checked, live_bad, live_unchecked = 0, [], 0
    manifest = read_md5_manifest(live_md5) if live_md5 else {}
    for row in rows:
        if not row.md5:
            continue
        got = manifest.get(row.live)
        if got is None:
            live_unchecked += 1
            continue
        live_checked += 1
        if not got.startswith(row.md5):
            live_bad.append("%s -- live file %s hashes %s, inventory records %s"
                            % (row, row.live, got[:len(row.md5)], row.md5))

    accounted = sum(len(v) for v in classes.values())
    say("inventory: %s", doc_path)
    say("repo ref:  %s (%s)", ref, head[:10])
    say("")
    say("rows parsed ................ %d", len(rows))
    for name in ("repo-pinned", "unreachable-pin", "repo-unpinned", "other-repo",
                 "no-source"):
        say("  %-24s %d", name + " " + "." * (22 - len(name)), len(classes[name]))
    say("rows accounted for ......... %d", accounted)
    say("repo claims hard-verified .. %d", hard_verified)
    say("rows marked %s ..... %d", MARKER, len(marked_ok))
    say("rows marked %s %d", PIN_MARKER + " " + "." * (11 - len(PIN_MARKER)),
        len(classes["unreachable-pin"]))
    say("")
    say("LIVE CLAIMS VERIFIED ....... %d of %d", live_checked, live_checked + live_unchecked)
    if not live_md5:
        say("  No --live-md5 manifest was given, so NOTHING here was compared against")
        say("  any host. A clean exit says the inventory is internally consistent and")
        say("  honestly flagged. It does NOT say the hosts match it.")
    say("")

    if accounted != len(rows):
        say("UNTRUSTWORTHY: %d rows parsed but %d classified -- a row fell through "
            "the classifier.", len(rows), accounted)
        return 2
    if problems:
        say("UNTRUSTWORTHY: %d candidate line(s) the grammar did not accept:", len(problems))
        for p in problems:
            say("  %s", p)
        return 2
    # A row that WAS assertable and failed is not "nothing was assertable", so the
    # findings have to be consulted before this rail fires -- otherwise a doc whose
    # only row is broken reports 2 (cannot trust itself) instead of 1 (it is wrong).
    if hard_verified == 0 and not findings and not live_bad:
        say("UNTRUSTWORTHY: not one row was hard-verifiable, so a clean result here "
            "would mean nothing.")
        return 2

    if (classes["other-repo"] or classes["no-source"] or classes["repo-unpinned"]
            or classes["unreachable-pin"]):
        say("NOT DECIDABLE FROM THIS REPO -- these rows need a host read, a sibling")
        say("checkout, or are upstream software; none of them was validated:")
        for name in ("unreachable-pin", "other-repo", "no-source", "repo-unpinned"):
            for row in classes[name]:
                say("  [%s] %s  %s", name, row.live, row.verdict)
        for note in unreachable_notes:
            say("%s", note)
        say("")

    if superseded:
        say("SUPERSEDED (marked, repo source moved past the pin -- a host read is the")
        say("only thing that settles what is installed):")
        for row in superseded:
            say("  %s", row.live)
        say("")

    rc = 0
    if live_bad:
        say("LIVE MISMATCH:")
        for f in live_bad:
            say("  %s", f)
        rc = 1
    if findings:
        say("REPO CLAIM FALSE:")
        for f in findings:
            say("  %s", f)
        rc = 1
    # Always gates: a pin nobody who clones can reach is a provenance hole, not
    # noise, and --warn-superseded deliberately does not cover it.
    if pin_findings:
        say("%s MARKER:", PIN_MARKER)
        for f in pin_findings:
            say("  %s", f)
        rc = 1
    if marker_findings:
        label = "SUPERSEDED MARKER (advisory)" if warn_superseded else "SUPERSEDED MARKER"
        say("%s:", label)
        for f in marker_findings:
            say("  %s", f)
        if not warn_superseded:
            rc = 1
    if rc == 0 and not marker_findings:
        say("CLEAN: every repo claim verifies and every flagged row is marked.")
    return rc


# --------------------------------------------------------------------------
# Self-test. Fixtures are DERIVED from this repo at run time -- a hand-written
# md5 or commit would rot, and a fixture that cannot fail is not a fixture.
# --------------------------------------------------------------------------
_DOC_HEAD = """# fixture

| verdict | meaning |
|---|---|
| MATCH | byte-identical to a blob |

## Data server

| path | md5 | verdict | source | note |
|---|---|---|---|---|
"""


def _fixture(rows):
    return _DOC_HEAD + "".join(rows) + "\n"


def selftest(repo_dir, out=sys.stdout):
    def say(fmt, *a):
        out.write((fmt % a if a else fmt) + "\n")

    git = Git(repo_dir)
    head = git.resolve("HEAD")
    if head is None:
        say("SELFTEST UNTRUSTWORTHY: %s is not a git checkout", repo_dir)
        return 2

    # A tracked path with at least two distinct blobs in history, found by
    # walking this script's own neighbours rather than naming one.
    subject = tip_md5 = old_commit = old_md5 = None
    candidates = subprocess.run(
        ["git", "ls-tree", "--name-only", "HEAD", "docs/", "scripts/"],
        cwd=repo_dir, stdout=subprocess.PIPE).stdout.decode("utf-8", "replace").split()
    for path in candidates:
        cur = git.blob("HEAD", path)
        if cur is None:
            continue
        cur_md5 = hashlib.md5(cur).hexdigest()
        revs = subprocess.run(
            ["git", "log", "--format=%H", "-20", "HEAD", "--", path],
            cwd=repo_dir, stdout=subprocess.PIPE).stdout.decode().split()
        for rev in revs[1:]:
            b = git.blob(rev, path)
            if b is not None and hashlib.md5(b).hexdigest() != cur_md5:
                subject, tip_md5 = path, cur_md5
                old_commit, old_md5 = rev, hashlib.md5(b).hexdigest()
                break
        if subject:
            break
    if not subject:
        say("SELFTEST UNTRUSTWORTHY: found no tracked path with two distinct blobs; "
            "the fixtures cannot be built.")
        return 2

    tip_commit = git.last_touch("HEAD", subject)
    say("selftest subject: %s", subject)
    say("  current  %s @ %s", tip_md5[:8], tip_commit[:10])
    say("  historic %s @ %s", old_md5[:8], old_commit[:10])
    say("")

    pipe = "| `/live/x` | `%s` | MATCH | `%s:%s` @ `%s` | %s |\n"
    cases = [
        ("pin is current, no marker", 0,
         _fixture([pipe % (tip_md5[:8], THIS_REPO, subject, tip_commit, "")])),
        ("pin is current but carries a stale marker", 1,
         _fixture([pipe % (tip_md5[:8], THIS_REPO, subject, tip_commit, MARKER)])),
        ("pin overtaken, marker missing", 1,
         _fixture([pipe % (old_md5[:8], THIS_REPO, subject, old_commit, "")])),
        ("pin overtaken, marker present", 0,
         _fixture([pipe % (old_md5[:8], THIS_REPO, subject, old_commit, MARKER)])),
        ("recorded md5 does not match the pinned blob", 1,
         _fixture([pipe % (tip_md5[:8], THIS_REPO, subject, old_commit, "")])),
        ("pinned path absent at its own commit", 1,
         _fixture([pipe % (tip_md5[:8], THIS_REPO, "no/such/file.sh", tip_commit, "")])),
        ("no row parses", 2, _DOC_HEAD),
        ("only rows this repo cannot decide", 2,
         _fixture(["| `/live/y` | `deadbeef` | EXTERNAL | — |  |\n"])),
        ("a bullet-shaped line the grammar rejects", 2,
         _fixture([pipe % (tip_md5[:8], THIS_REPO, subject, tip_commit, "")])
         + "- `/live/z` `abcdef12` is not a row\n"),
        ("bullet row, pin overtaken, marker present", 0,
         _fixture([pipe % (tip_md5[:8], THIS_REPO, subject, tip_commit, "")])
         + "\n- `/live/w` `%s` = `%s:%s` @ `%s` %s\n"
         % (old_md5[:8], THIS_REPO, subject, old_commit, MARKER)),
        ("pin unreachable, marker missing", 1,
         _fixture([pipe % (tip_md5[:8], THIS_REPO, subject, tip_commit, ""),
                   pipe % ("deadbeef", THIS_REPO, subject, "0" * 40, "")])),
        ("pin unreachable, marker present", 0,
         _fixture([pipe % (tip_md5[:8], THIS_REPO, subject, tip_commit, ""),
                   pipe % ("deadbeef", THIS_REPO, subject, "0" * 40, PIN_MARKER)])),
        ("reachable pin wrongly carrying the pin marker", 1,
         _fixture([pipe % (tip_md5[:8], THIS_REPO, subject, tip_commit, PIN_MARKER)])),
        ("pin marker does not satisfy the supersession leg", 1,
         _fixture([pipe % (old_md5[:8], THIS_REPO, subject, old_commit, PIN_MARKER)])),
        ("bullet row, pin overtaken, marker missing", 1,
         _fixture([pipe % (tip_md5[:8], THIS_REPO, subject, tip_commit, "")])
         + "\n- `/live/w` `%s` = `%s:%s` @ `%s`\n"
         % (old_md5[:8], THIS_REPO, subject, old_commit)),
    ]

    failures = 0
    tmpdir = tempfile.mkdtemp(prefix="inv-selftest-")
    sink = open(os.devnull, "w")
    try:
        for name, want, body in cases:
            p = os.path.join(tmpdir, "f.md")
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(body)
            got = check(p, repo_dir, "HEAD", out=sink)
            ok = got == want
            failures += 0 if ok else 1
            say("%-4s %-52s want %d got %d", "ok" if ok else "FAIL", name, want, got)

        # Live-manifest leg, both directions, on a real row.
        p = os.path.join(tmpdir, "f.md")
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_fixture([pipe % (tip_md5[:8], THIS_REPO, subject, tip_commit, "")]))
        for name, digest, want in (("live manifest agrees", tip_md5, 0),
                                   ("live manifest disagrees", "0" * 32, 1)):
            mp = os.path.join(tmpdir, "live.md5")
            with open(mp, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("%s  /live/x\n" % digest)
            got = check(p, repo_dir, "HEAD", live_md5=mp, out=sink)
            ok = got == want
            failures += 0 if ok else 1
            say("%-4s %-52s want %d got %d", "ok" if ok else "FAIL", name, want, got)
    finally:
        sink.close()
        for f in os.listdir(tmpdir):
            os.unlink(os.path.join(tmpdir, f))
        os.rmdir(tmpdir)

    say("")
    say("selftest: %d case(s) failed", failures)
    return 1 if failures else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--doc", default=DEFAULT_DOC)
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    ap.add_argument("--ref", default="HEAD",
                    help="the revision that counts as 'the repo now'. HEAD by "
                         "default so a PR is judged against its own content; "
                         "origin/main is often absent in CI checkouts.")
    ap.add_argument("--live-md5", help="md5sum-format file read off a host")
    ap.add_argument("--warn-superseded", action="store_true",
                    help="report missing/stale SUPERSEDED markers without failing")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest(args.repo)
    return check(args.doc, args.repo, args.ref, args.live_md5, args.warn_superseded)


if __name__ == "__main__":
    sys.exit(main())
