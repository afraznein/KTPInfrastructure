#!/usr/bin/env python3
"""Install a built game-files manifest onto the AC API host, gated.

`build-game-files-manifest.py` installs nothing. It writes a JSON file where you
point `--out` and stops; nothing reaches a player until someone copies that file
into place on the data server. That copy was a hand-run `scp` + `cp` pair, and it
is the step where enforcement actually changes for every player with the client
installed. This is that step, with the acknowledgement attached to it.

What it does, in order:

  1. resolves the installed manifest path from the API's own configuration, so the
     gate compares against — and later replaces — the file the API is really serving;
  2. downloads it and prints a scope diff of what the install would change, rendered
     by the generator's own `format_scope_diff` so the two steps describe a change
     the same way;
  3. refuses, unless every change it gates on — path membership, severity, and allowed
     alternate hashes — is acknowledged by an exact count;
  4. takes the backup itself;
  5. writes atomically and verifies the bytes that landed.

⚠️ The gate is ARMED BY DEFAULT — that is the whole point of moving it here.
The generator's `--gate-scope` is opt-in because a regeneration reaches nobody:
arming it by default would be friction where nothing happens to a player. Here
the opposite holds. Every run of this script changes what players are checked
against, so the acknowledgement belongs on by default and `--no-gate` is the
break-glass, not the workflow.

🔴 Severity is gated, not just membership. `review` -> `violation` widens
enforcement without adding a single path: the file was already hashed and already
reported, and the flip is what makes a mismatch score against the player. A
membership-only gate is blind to it, and so is `_meta.version` — that hash covers
paths, hashes and allowed alternates, so a severity-only change leaves the version
string untouched and every version-based identity check agrees that nothing moved.
It has happened: six lowered weapon models (`p_*_l.mdl`) went review -> violation
between the 2026-05-07 manifest and the installed one.

⚠️ It does NOT gate a changed sha256 on a path already in scope, which re-scores every
player still on the old bytes. That is inherited from the generator's ruling (files
legitimately change on the fleet tree, and a gate that fires on every one becomes noise
and gets rubber-stamped) and it is a stated gap, not an oversight — the re-hash count is
printed.

⛔ The only paths this writes are the manifest, its backup, and a staged temp beside it.
`/opt/ktp-ac-api/` also holds `uploads/`, the evidence corpus, and `releases/`, a client
binary copy — so nothing here lists, globs or operates on a directory at all.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import paramiko

# Remote-writing entry point: refuse to run from a checkout behind origin/main
# (ktp_script_freshness.py). The failure mode is this script's own reason for
# existing — a copy predating the severity gate would install a widening and
# report success, because a check it has never heard of cannot decline.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ktp_script_freshness import require_current  # noqa: E402


# Where the API looks when `GameFilesManifestPath` is unset — the default in
# KTPAntiCheat.Api/Program.cs. Used only as the fallback for --installed-path;
# the configured value wins, because a manifest installed at the documented path
# while the API reads another one is an install that changed nothing.
DEFAULT_MANIFEST_PATH = "/opt/ktp-ac-api/game_files_manifest.json"
DEFAULT_APPSETTINGS = "/opt/ktp-ac-api/appsettings.json"

# Enforcement strength, weakest first. A move UP this list widens what a player is
# scored on; a move DOWN narrows it. `review` is captured, reported and shown to an
# admin, and never reaches a verdict; `violation` counts.
#
# Deliberately not a dict lookup with a default: an unrecognised severity must not
# be ranked as harmless. See `classify_severity_change`.
SEVERITY_RANK = {"review": 0, "violation": 1}


# --------------------------------------------------------------------------
# Generator reuse
# --------------------------------------------------------------------------

def load_generator(script_dir=None):
    """The generator module, loaded by path because its filename has hyphens.

    The diff and its rendering live there and are pinned by
    `tests/unit/test_game_files_manifest_diff.py`. Importing them is what keeps the
    two steps from growing separate vocabularies for the same change — an operator
    who has read one diff should not have to learn a second layout to read this one.
    """
    script_dir = Path(script_dir or Path(__file__).resolve().parent)
    src = script_dir / "build-game-files-manifest.py"
    if not src.exists():
        raise FileNotFoundError(
            f"{src} not found. This script reuses the generator's scope diff, so the two "
            "travel together. Take both:\n"
            "  git archive origin/main scripts/install-game-files-manifest.py "
            "scripts/build-game-files-manifest.py | tar -x -C <workdir>"
        )
    spec = importlib.util.spec_from_file_location("_ktp_game_files_manifest", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# Severity gate — the change a membership gate cannot see
# --------------------------------------------------------------------------

def classify_severity_change(before, after):
    """'widened', 'narrowed' or 'unknown' for one severity transition.

    `unknown` covers any severity this script has no rank for, in either direction,
    and it gates. A severity added to the generator's policy later would otherwise
    arrive here and be silently ranked as harmless by a `.get(s, 0)` — the gate would
    keep passing while the meaning of the change was exactly what nobody had looked at.
    Failing closed on a string we do not understand costs one refusal and one commit.
    """
    if before not in SEVERITY_RANK or after not in SEVERITY_RANK:
        return "unknown"
    if SEVERITY_RANK[after] > SEVERITY_RANK[before]:
        return "widened"
    if SEVERITY_RANK[after] < SEVERITY_RANK[before]:
        return "narrowed"
    # Unreachable today: no two ranks are equal, and a transition is only reported when
    # the strings differ. Kept so a future same-rank pair is a no-op, not a surprise.
    return None


def severity_transitions(diff):
    """Group the diff's severity flips into the three buckets the gate counts.

    Reads `diff["severity_changed"]`, which the generator computes over paths present
    on BOTH sides. So these never overlap with added/removed, and a path cannot be
    counted twice by two halves of the same gate.
    """
    buckets = {"widened": [], "narrowed": [], "unknown": []}
    for path, before, after in diff.get("severity_changed", []):
        kind = classify_severity_change(before, after)
        if kind:
            buckets[kind].append((path, before, after))
    return buckets


def alternate_transitions(previous, candidate, enforced_severity=None):
    """Allowed-alternate-hash changes, the third axis neither existing control sees.

    🔴 **Dropping an operator-curated alternate widens enforcement for every player
    holding that file, with no path added, no severity moved and no hash changed.** The
    generator attaches `allowed_alternate_hashes` and its `diff_manifests` does not
    compare them, so such an install reports `no change: same paths, same severities,
    same hashes` — the worst case this tool exists to catch, described in reassuring
    words. The generator's own note on the four curated entries states the blast radius:
    without them they surface as false-positive violations on every legitimate player.

    Computed here rather than taken from the generator's diff, because the diff has no
    field for it. A change counts when the path is enforced on either side: an alternate
    on a `review` path never scores in either direction, and requiring enforcement on
    BOTH sides would miss the case where severity and alternates move together.
    """
    enforced = enforced_severity or (lambda e: e.get("severity", "violation") != "review")
    prev = {e["path"]: e for e in previous.get("files", [])}
    cur = {e["path"]: e for e in candidate.get("files", [])}

    dropped, gained = [], []
    for path in sorted(set(prev) & set(cur)):
        before, after = prev[path], cur[path]
        if not (enforced(before) or enforced(after)):
            continue
        was = set(before.get("allowed_alternate_hashes") or [])
        now = set(after.get("allowed_alternate_hashes") or [])
        if was - now:
            dropped.append((path, sorted(was - now)))
        if now - was:
            gained.append((path, sorted(now - was)))
    return dropped, gained


def format_alternate_verdict(dropped, gained):
    """Spelled out per path — these are a handful of curated entries, and each one is a
    decision about whether a legitimate community file starts failing."""
    lines = []
    for rows, label, effect in ((dropped, "ALTERNATES DROPPED", "now score against a holder"),
                                (gained, "ALTERNATES ADDED", "no longer score")):
        if not rows:
            continue
        lines.append(f"  {label} — {len(rows)} path(s), hashes that {effect}:")
        for path, hashes in rows:
            lines.append(f"    {path}")
            lines += [f"      {h}" for h in hashes]
    return lines


def format_severity_verdict(buckets):
    """Which direction each of the diff's severity flips went.

    The generator's diff has already listed every flipped path under SEVERITY CHANGED.
    What it cannot say is which of them widen, and that is the only thing the gate acts
    on, so this classifies rather than re-listing: a count per direction, and the
    transitions that produced it. Unrecognised severities DO get their paths, because
    they refuse and the reader has to go and look at them.
    """
    if not any(buckets.values()):
        return []
    lines = ["  severity direction (SEVERITY CHANGED above, classified):"]
    for kind, label in (("widened", "WIDENS enforcement "),
                        ("narrowed", "NARROWS enforcement")):
        rows = buckets[kind]
        if rows:
            pairs = Counter(f"{was} -> {now}" for _, was, now in rows)
            detail = ", ".join(f"{t} x{n}" if n > 1 else t for t, n in pairs.most_common())
            lines.append(f"    {label}: {len(rows)}  ({detail})")
    if buckets["unknown"]:
        lines.append(f"    UNRECOGNISED     : {len(buckets['unknown'])} — no rank for these:")
        lines += [f"      {p}: {was} -> {now}" for p, was, now in buckets["unknown"]]
    return lines


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

class Acknowledgements:
    """The four counts an operator can supply, and whether any were.

    Counts rather than booleans, for the reason the generator's gate uses counts: a
    `--accept-added 12` pasted out of a runbook stops agreeing the moment the install
    would add a thirteenth path, which is precisely when someone needs to look again.
    A boolean would keep passing forever.
    """

    def __init__(self, added=None, removed=None, widened=None, narrowed=None,
                 alternates_dropped=None, alternates_gained=None):
        self.added = added
        self.removed = removed
        self.widened = widened
        self.narrowed = narrowed
        self.alternates_dropped = alternates_dropped
        self.alternates_gained = alternates_gained


def gate_install(diff, ack, enforced_changes, alternates=((), ()), out=None):
    """True to proceed with the copy, False to refuse.

    Six independent counts, each refusing on its own. They are separate flags rather
    than one total because they are different decisions: a path entering enforcement,
    a path leaving it, a file starting to score, a file stopping, and the two directions
    of an allowed-alternate change. Collapsing them into one number would let an
    addition and a removal cancel out to zero.

    `unknown` severity transitions take no accept flag at all. There is nothing to
    acknowledge a count of when the script cannot say which direction the change went;
    the fix is to teach SEVERITY_RANK the new value, in a commit someone reviews.

    `out` is resolved per call, never bound as a default, so a caller that redirected
    stderr still sees the refusals.
    """
    out = sys.stderr if out is None else out
    sev = severity_transitions(diff)
    ok = True

    checks = (
        ("--accept-added", len(enforced_changes(diff["added"])), ack.added,
         "enforced path(s) entering scope"),
        ("--accept-removed", len(enforced_changes(diff["removed"])), ack.removed,
         "enforced path(s) leaving scope"),
        ("--accept-widened", len(sev["widened"]), ack.widened,
         "path(s) whose severity now scores against a player"),
        ("--accept-narrowed", len(sev["narrowed"]), ack.narrowed,
         "path(s) whose severity no longer scores"),
        ("--accept-alternates-dropped", len(alternates[0]), ack.alternates_dropped,
         "enforced path(s) losing an allowed alternate hash"),
        ("--accept-alternates-gained", len(alternates[1]), ack.alternates_gained,
         "enforced path(s) gaining an allowed alternate hash"),
    )

    for flag, observed, accepted, noun in checks:
        if observed == 0 and accepted is None:
            continue
        if accepted is None:
            print(f"  REFUSED: {observed} {noun}. Read the diff above, then re-run with "
                  f"{flag} {observed}.", file=out)
            ok = False
        elif accepted != observed:
            # Including when `observed` is now ZERO. A count supplied for a change that
            # has since disappeared is the same staleness as a count that is too low, and
            # ignoring it would let a run be waved through on an acknowledgement of
            # something that is no longer in the diff.
            print(f"  REFUSED: {flag} {accepted} does not match the {observed} {noun}. "
                  "The manifest changed since you looked.", file=out)
            ok = False
        else:
            print(f"  accepted: {observed} {noun} ({flag} {accepted})", file=out)

    if sev["unknown"]:
        print(f"  REFUSED: {len(sev['unknown'])} severity transition(s) this script cannot "
              "rank. No --accept flag covers them: add the severity to SEVERITY_RANK in "
              "scripts/install-game-files-manifest.py first.", file=out)
        ok = False

    if ok and not any(observed for _, observed, _, _ in checks):
        print("  gate: nothing enforced entered or left scope, no severity moved, and no "
              "allowed alternate changed.", file=out)
    return ok


# --------------------------------------------------------------------------
# Remote side
# --------------------------------------------------------------------------

def resolve_installed_path(ssh, appsettings_path=DEFAULT_APPSETTINGS,
                           fallback=DEFAULT_MANIFEST_PATH, out=None):
    """The manifest path the API actually reads.

    `GameFilesManifestPath` in appsettings.json overrides the compiled-in default, so
    a run that assumed the default would happily back up and replace a file the API
    never opens — an install that changed nothing, reporting success. Every failure to
    read the config is announced and falls back rather than aborting: appsettings.json
    is mode 600 and holds secrets, and an unreadable one is a permissions story, not a
    reason to refuse to install.
    """
    out = sys.stderr if out is None else out
    program = ("import json;"
               f"print(json.load(open({appsettings_path!r})).get('GameFilesManifestPath') or '')")
    # Timeout, like every remote call in the generator: without one a wedged host hangs
    # the install at its first remote call, with nothing printed to say where.
    _, stdout, stderr = ssh.exec_command("python3 -c " + shlex.quote(program), timeout=30)
    value = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    if value and (not value.startswith("/") or value.endswith("/")):
        print(f"  installed path: {fallback} (GameFilesManifestPath is {value!r}, which is "
              "not an absolute file path — ignoring it)", file=out)
        return fallback
    if value:
        if value != fallback:
            print(f"  installed path: {value} (from GameFilesManifestPath, NOT the "
                  f"default {fallback})", file=out)
        return value
    reason = err.splitlines()[-1] if err else "key absent"
    print(f"  installed path: {fallback} (config gave nothing: {reason})", file=out)
    return fallback


def read_remote_manifest(sftp, path):
    """(manifest, raw_bytes, reason). `manifest` is None unless it parsed as one.

    🔑 `raw_bytes` is returned whenever the READ succeeded, even when the parse did not,
    and the two answer different questions. "Is there a baseline to gate against?" is
    about the parse. "Is there a file here that must be backed up before I replace it?"
    is about the read — and conflating them means an installed manifest that has become
    unparseable (truncated by a half-finished hand copy, say) is treated as absent and
    overwritten with no backup, which is precisely the file you would most want back.

    The bytes also spare the byte-identical check a second read of a 190KB file.
    """
    try:
        with sftp.open(path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        return None, None, f"{path} could not be read ({exc})"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, raw, f"{path} is not valid JSON ({exc})"
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        return None, raw, f"{path} has no files[] — not a manifest"
    return data, raw, None


SAFE_REASON = re.compile(r"[^A-Za-z0-9._-]+")


def backup_name(installed_path, reason, when=None, attempt=0):
    """`<installed>.bak-<reason>-<YYYYMMDD>`, matching what is already on the box.

    The reason is squeezed to a safe token because it lands in a shell-free SFTP path
    but still has to be readable in an `ls`, and because a stray quote or slash in an
    operator's `--reason` would otherwise write the backup somewhere other than beside
    the manifest.

    A day-granular name collides on the second install of a day under the same reason,
    and the collision would overwrite the only copy of what was live this morning with a
    copy of what has been live since lunchtime — the rollback target quietly becoming the
    thing you are rolling back from. `attempt` gains the time, a shape already on the box.
    """
    when = when or datetime.now(timezone.utc)
    token = SAFE_REASON.sub("-", reason).strip("-").lower() or "install"
    name = f"{installed_path}.bak-{token}-{when.strftime('%Y%m%d')}"
    return name if attempt == 0 else f"{name}-{when.strftime('%H%M%S')}"


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def take_backup(sftp, installed_path, reason, out=None):
    """Copy the live manifest aside, refusing to clobber an existing backup.

    🔑 The exclusive create is the whole guarantee. A listing-then-choose would be a
    CHECK, and a check that cannot list the directory has to either refuse or fail open
    — and failing open silently re-enables the overwrite it was added to prevent. `"wx"`
    is O_EXCL: the server refuses the create, so no answer from us is needed and no
    directory has to be read. That is also why nothing here lists, globs or touches a
    directory; the manifest's neighbours are `uploads/` (the evidence corpus) and
    `releases/`.
    """
    out = sys.stderr if out is None else out

    # Read the source ONCE, outside the retry. Inside it, a failure to read the live
    # manifest would be indistinguishable from a name collision, and the run would
    # report "exists; adding the time" about a file that is fine and a read that is not.
    with sftp.open(installed_path, "rb") as src:
        live = src.read()

    for attempt in (0, 1):
        backup = backup_name(installed_path, reason, attempt=attempt)
        try:
            with sftp.open(backup, "wx") as dst:
                dst.write(live)
        except OSError as exc:
            if attempt == 0:
                print(f"  backup:    {backup} exists ({exc}); adding the time", file=out)
                continue
            raise
        sftp.chmod(backup, 0o644)
        print(f"  backup:    {backup}", file=out)
        return backup
    raise RuntimeError("unreachable")


def install(sftp, installed_path, payload, reason, had_previous, out=None):
    """Back up, verify, then publish. Returns the backup path, or None on a first install.

    🔴 The read-back happens BEFORE the rename, not after. Verifying afterwards detects a
    bad write only once the API is already serving it, and with `max-age=300` on the
    responses it has propagated by the time anyone reads the error. It is not theoretical:
    paramiko's `SFTPFile._close()` swallows the errors raised by the CMD_CLOSE round-trip,
    so a server-side failure at flush time need not raise at all — the read-back is the
    only reliable check, and it is worth nothing one step too late. Verifying the staged
    copy turns this from detection into prevention, which is what the staging is for.

    The staged file sits in the manifest's own directory rather than /tmp because the
    rename that publishes it is only atomic within one filesystem, and it carries the pid
    so two runs cannot interleave on one temp path.
    """
    out = sys.stderr if out is None else out
    backup = None
    if had_previous:
        backup = take_backup(sftp, installed_path, reason, out=out)
    else:
        print("  backup:    none taken — nothing was installed there", file=out)

    staged = f"{installed_path}.installing.{os.getpid()}"
    try:
        with sftp.open(staged, "wb") as f:
            f.write(payload)
        sftp.chmod(staged, 0o644)

        with sftp.open(staged, "rb") as f:
            landed = f.read()
        if sha256_bytes(landed) != sha256_bytes(payload):
            raise RuntimeError(
                f"{staged} does not match what was sent, so it was not published. "
                f"{installed_path} is untouched and still live.")

        # posix_rename, not rename: plain SFTP rename is specified to FAIL when the target
        # exists, and the target always exists here. A server without the OpenSSH extension
        # raises, which is the right outcome — the alternative is an unlink-then-write with
        # a window where the API 404s.
        sftp.posix_rename(staged, installed_path)
    except Exception:
        # Broad on purpose: a dead channel raises SSHException, not an OSError, and
        # letting that escape here would leave the staged file behind AND mask the
        # original failure with a second one.
        try:
            sftp.remove(staged)
        except Exception:
            print(f"  WARNING: could not remove the staged file {staged}; delete it by "
                  "hand. It is not live and the API never reads it.", file=out)
        raise
    return backup


def load_local_manifest(path):
    raw = Path(path).read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise ValueError(f"{path} has no files[] — not a manifest")
    return data, raw


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="Install a built game-files manifest onto the AC API host, gated.")
    ap.add_argument("--manifest", required=True,
                    help="Local manifest to install (the generator's --out)")
    ap.add_argument("--server", default=os.environ.get("KTP_AC_API_HOST"),
                    help="AC API host (default: $KTP_AC_API_HOST)")
    ap.add_argument("--user", default="root")
    ap.add_argument("--ssh-key", default=None,
                    help="Private key (default: $KTP_AC_API_SSH_KEY, else ~/.ssh/id_ed25519)")
    ap.add_argument("--reason", required=True,
                    help="Why this is being installed. Names the backup, so make it findable "
                         "in an ls six months from now (e.g. pre-weapon-kit).")
    ap.add_argument("--installed-path", default=None,
                    help="Manifest path on the host (default: read GameFilesManifestPath from "
                         f"{DEFAULT_APPSETTINGS})")
    ap.add_argument("--appsettings", default=DEFAULT_APPSETTINGS,
                    help=f"API config to resolve the manifest path from (default: {DEFAULT_APPSETTINGS})")
    ap.add_argument("--diff-limit", type=int, default=None,
                    help="Paths listed per origin in the diff, 0 for all (default: the "
                         "generator's default)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the diff and the gate's verdict, then stop before any write.")
    ap.add_argument("--no-gate", action="store_true",
                    help="BREAK GLASS: install without acknowledging anything. The --accept "
                         "flags are the normal override; this is for a first install or a "
                         "deliberate re-scope, and it is announced in the output.")
    ap.add_argument("--accept-added", type=int, default=None, metavar="N",
                    help="Acknowledge exactly N enforced paths entering scope.")
    ap.add_argument("--accept-removed", type=int, default=None, metavar="N",
                    help="Acknowledge exactly N enforced paths leaving scope.")
    ap.add_argument("--accept-widened", type=int, default=None, metavar="N",
                    help="Acknowledge exactly N paths whose severity now scores (review -> violation).")
    ap.add_argument("--accept-narrowed", type=int, default=None, metavar="N",
                    help="Acknowledge exactly N paths whose severity no longer scores.")
    ap.add_argument("--accept-alternates-dropped", type=int, default=None, metavar="N",
                    help="Acknowledge exactly N enforced paths losing an allowed alternate "
                         "hash. Dropping one makes a legitimate community file score.")
    ap.add_argument("--accept-alternates-gained", type=int, default=None, metavar="N",
                    help="Acknowledge exactly N enforced paths gaining an allowed alternate hash.")
    return ap


def connect(server, user, key_path):
    ssh = paramiko.SSHClient()
    # Loaded before the policy so AutoAdd only ever covers a genuinely unknown host: a
    # CHANGED key then raises BadHostKeyException instead of being accepted in silence,
    # which for the script that replaces what every client is checked against is the
    # difference between a warning and none.
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(server, username=user, key_filename=key_path)
    return ssh


def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    # After parse_args so --help answers without a network, and before --dry-run: a plan
    # printed by a stale copy is wrong in exactly the way that is hard to notice. `also`
    # covers the generator because its diff is what this gate decides on — a current
    # installer reading a stale diff would refuse and accept the wrong things.
    require_current(__file__, also=["build-game-files-manifest.py"],
                    purpose="replace the manifest every AC client is checked against")

    gen = load_generator()
    err = sys.stderr

    if not args.server:
        sys.exit("--server is required (or set $KTP_AC_API_HOST). No host is compiled in: "
                 "this script writes to whatever it is pointed at.")
    if args.no_gate and any(v is not None for v in
                            (args.accept_added, args.accept_removed, args.accept_widened,
                             args.accept_narrowed, args.accept_alternates_dropped,
                             args.accept_alternates_gained)):
        sys.exit("--no-gate with an --accept count is contradictory: the counts ARE the "
                 "acknowledgement. Drop --no-gate and let them be checked.")

    try:
        candidate, payload = load_local_manifest(args.manifest)
    except (OSError, ValueError) as exc:
        sys.exit(f"candidate manifest unusable: {exc}")

    key_path = (args.ssh_key or os.environ.get("KTP_AC_API_SSH_KEY")
                or str(Path.home() / ".ssh" / "id_ed25519"))
    ssh = connect(args.server, args.user, key_path)
    try:
        sftp = ssh.open_sftp()
        if args.installed_path:
            installed_path = args.installed_path
            print(f"  installed path: {installed_path} (--installed-path; the API's "
                  "configuration was NOT consulted)", file=err)
        else:
            installed_path = resolve_installed_path(ssh, args.appsettings,
                                                    DEFAULT_MANIFEST_PATH, out=err)
        previous, previous_raw, unavailable = read_remote_manifest(sftp, installed_path)

        # A file that is THERE but cannot be read is not a first install and must never
        # be treated as one: there is no way to copy it aside, so replacing it destroys
        # the only copy. Separated from ENOENT by a stat, because the read failure alone
        # cannot tell the two apart and the refusal below would otherwise point an
        # operator at --no-gate — the one flag that overwrites without a backup.
        if previous_raw is None:
            try:
                sftp.stat(installed_path)
            except OSError:
                pass
            else:
                print(f"\nREFUSED: {installed_path} exists but could not be read "
                      f"({unavailable}). It cannot be backed up, so it must not be "
                      "replaced. --no-gate does not cover this: fix the file first.",
                      file=err)
                return 2

        # Byte-identical installs are the one case worth short-circuiting: they would
        # otherwise take a backup of a file against its own twin and move the mtime,
        # which is the only thing the API's cache keys on, for no change at all.
        if previous_raw == payload:
            print("\nAlready installed: byte-identical to what is on the host. "
                  "Nothing written, no backup taken.", file=err)
            return 0

        limit = (gen.DIFF_LIST_LIMIT_DEFAULT if args.diff_limit is None else args.diff_limit)
        diff = gen.diff_manifests(previous, candidate) if previous is not None else None
        for line in gen.scope_diff_lines(previous, candidate, installed_path, unavailable,
                                         limit, diff=diff):
            print(line, file=err)

        alternates = (alternate_transitions(previous, candidate)
                      if previous is not None else ((), ()))
        if diff is not None:
            for line in format_severity_verdict(severity_transitions(diff)):
                print(line, file=err)
            for line in format_alternate_verdict(*alternates):
                print(line, file=err)

        print("\n=== Install gate ===", file=err)
        if args.no_gate:
            # Loud, and above the write rather than after it: this line is the only
            # record that an install went in unexamined.
            print("  GATE DISARMED (--no-gate). Nothing about this change was "
                  "acknowledged.", file=err)
        elif diff is None:
            # The generator warns and writes anyway here. This refuses. A regeneration
            # with no baseline reaches nobody; an install with no baseline puts an
            # unreviewed manifest in front of every player, and "the gate could not
            # compare" must never read as "the gate passed".
            print(f"  REFUSED: no installed manifest to compare against "
                  f"({unavailable}). A gate with no baseline cannot pass. If this is a "
                  "genuine first install, say so with --no-gate.", file=err)
            return 2
        else:
            ack = Acknowledgements(args.accept_added, args.accept_removed,
                                   args.accept_widened, args.accept_narrowed,
                                   args.accept_alternates_dropped,
                                   args.accept_alternates_gained)
            if not gate_install(diff, ack, gen.enforced_changes, alternates, out=err):
                print(f"  {installed_path} left UNCHANGED.", file=err)
                return 2

        if args.dry_run:
            print("  --dry-run: stopping before the copy.", file=err)
            return 0

        # `previous_raw`, not `previous`: a file that exists but no longer parses still
        # gets backed up before it is replaced. See read_remote_manifest.
        backup = install(sftp, installed_path, payload, args.reason,
                         had_previous=previous_raw is not None, out=err)

        meta = candidate.get("_meta", {})
        print("\n=== Installed ===", file=err)
        print(f"  path:      {installed_path}", file=err)
        print(f"  version:   {meta.get('version')}   (severity is NOT in this hash)", file=err)
        print(f"  severity:  {meta.get('by_severity')}", file=err)
        print(f"  total:     {meta.get('total_files')} files", file=err)
        print(f"  sha256:    {sha256_bytes(payload)}", file=err)
        if backup:
            print(f"  rollback:  cp {backup} {installed_path}", file=err)
        else:
            print("  rollback:  none — there was nothing installed to keep", file=err)
        print("  No restart: the API re-reads on mtime change. Responses carry "
              "max-age=300, so allow a few minutes.", file=err)
        return 0
    finally:
        ssh.close()


if __name__ == "__main__":
    sys.exit(main())
