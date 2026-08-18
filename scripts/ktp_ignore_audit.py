"""Audit the credential rules in .gitignore against what they actually protect.

WHY. Five ignore rules were commented out on 2026-08-18 as "vestigial", because
the files they named no longer existed locally. That reasoning is inverted for a
credential rule: a rule covering an absent filename costs nothing, and is the
entire protection if the file comes back. Two of the five had been deleted
*because* they carried secrets, which makes them the highest-value guards rather
than the lowest. This audit exists so the judgement is made by a tool against
evidence rather than by hand against a directory listing.

ERRORS fail the build; they are claims the repo can disprove on its own:
  - a pattern in the region with no tag
  - @guard whose file exists (it is protecting something now -- retag)
  - @privacy or @guard with no `# why:` line
  - @secret whose file is absent (retag @guard, and keep the rule)

WARNINGS do not fail by default, because clearing them needs an inventory this
repo must never contain. Run with --strict once the inventory covers every
credential class, and CI will hold the line from then on.
"""

from __future__ import annotations

import re
from pathlib import Path

REGION_START = "# === CREDENTIAL RULES: tagged, audited by ktp_secret_scan audit-ignore ==="
REGION_END = "# === END CREDENTIAL RULES ==="

_TAG_RE = re.compile(r"^#\s*(@secret|@hostinfo|@guard|@privacy|@local)\b")
_WHY_RE = re.compile(r"^#\s*why:\s*\S")

NEEDS_WHY = {"@guard", "@privacy"}


def _parse(gitignore: Path):
    """Return (entries, errors, blind); entry = (lineno, tag, pattern, has_why).

    `blind` means the audit could not locate the region at all -- a different
    outcome from "the region is fine": one is a broken check, the other a pass."""
    lines = gitignore.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index(REGION_START)
        end = lines.index(REGION_END)
    except ValueError:
        return [], [], True

    entries, errors = [], []
    pending_tag, pending_why = None, False

    for lineno, raw in enumerate(lines[start + 1:end], start=start + 2):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            match = _TAG_RE.match(line)
            if match:
                pending_tag, pending_why = match.group(1), False
            elif _WHY_RE.match(line):
                pending_why = True
            continue
        if pending_tag is None:
            errors.append(f".gitignore:{lineno}: pattern {line!r} has no @tag above it")
        else:
            entries.append((lineno, pending_tag, line, pending_why))
        pending_tag, pending_why = None, False

    return entries, errors, False


def audit(root: Path, strict: bool = False, structure_only: bool = False) -> int:
    """0 when every tag still says something true, 1 on error, 2 when blind.

    ⚠️ Existence and content checks are WORKTREE-LOCAL. Ignored files are by
    definition untracked, so a fresh clone or a CI checkout holds none of them
    and every @secret would read as "absent -> retag @guard" -- advice that is
    wrong everywhere the files actually live. CI must pass structure_only=True;
    the content half belongs on the operator's box.
    """
    from ktp_secret_scan import load_inventory, load_hostinfo, read_text_safe

    entries, errors, blind = _parse(root / ".gitignore")
    if blind:
        print("  BROKEN: .gitignore credential region markers missing -- "
              "nothing is being audited")
        return 2
    warnings: list[str] = []

    if structure_only:
        print("  ignore audit: STRUCTURE ONLY (tags and why: lines; no file checks)")
    else:
        # Refuse to emit a wall of false "absent" errors in a tree that simply
        # never had these files. That signature means the caller wanted
        # structure_only, not that every tag is wrong.
        present = sum(1 for _, _, pattern, _ in entries
                      if (root / pattern.rstrip("/")).exists())
        if entries and present == 0:
            print("  BROKEN: content mode, but none of the tagged files exist here. "
                  "This is a fresh checkout -- use --structure-only, or run from the "
                  "working copy that holds them.")
            return 2

    live, retired = load_inventory()
    secret_values = live + retired
    host_values = load_hostinfo()

    def _contains(path: Path, needles: list[str]) -> bool | None:
        """True/False, or None when the file cannot be read as text."""
        text = read_text_safe(path)
        if text is None:
            return None
        return any(n in text for n in needles)

    for lineno, tag, pattern, has_why in entries:
        target = root / pattern.rstrip("/")
        exists = target.exists()

        if tag in NEEDS_WHY and not has_why:
            errors.append(f".gitignore:{lineno}: {tag} {pattern!r} needs a `# why:` line")

        if structure_only:
            continue

        if tag == "@guard":
            if exists:
                errors.append(
                    f".gitignore:{lineno}: @guard {pattern!r} but the file EXISTS -- "
                    "retag @secret/@hostinfo/@privacy so it gets checked"
                )
        elif tag == "@secret":
            if not exists:
                errors.append(
                    f".gitignore:{lineno}: @secret {pattern!r} is absent -- retag "
                    "@guard and KEEP the rule; absent files are what guards are for"
                )
            elif target.is_file() and _contains(target, secret_values) is False:
                warnings.append(
                    f".gitignore:{lineno}: @secret {pattern!r} holds no inventory "
                    "value -- add its secret to the inventory, track the file, or "
                    "retag @hostinfo/@privacy"
                )
        elif tag == "@hostinfo":
            if not exists:
                errors.append(
                    f".gitignore:{lineno}: @hostinfo {pattern!r} is absent -- retag @guard"
                )
            elif not host_values:
                warnings.append(
                    f".gitignore:{lineno}: @hostinfo {pattern!r} unverified -- the "
                    "inventory declares no hostinfo values"
                )
            elif target.is_file() and _contains(target, host_values) is False:
                warnings.append(
                    f".gitignore:{lineno}: @hostinfo {pattern!r} carries no known fleet "
                    "address -- retag, or track it"
                )

    print(f"  ignore audit: {len(entries)} tagged rule(s)")
    # An empty region with no errors means the markers are there but hold
    # nothing -- still blind, and still not a pass.
    if not entries and not errors:
        print("  BROKEN: region is empty -- the audit is scanning nothing")
        return 2

    for err in errors:
        print(f"    ERROR   {err}")
    for warn in warnings:
        print(f"    warn    {warn}")

    if errors:
        print(f"  ignore audit: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    if warnings and strict:
        print(f"  ignore audit: {len(warnings)} warning(s), --strict -> failing")
        return 1
    if warnings:
        print(f"  ignore audit: no errors, {len(warnings)} warning(s) "
              "(complete the inventory, then enable --strict)")
        return 0
    print("  ignore audit: every tag still says something true")
    return 0
