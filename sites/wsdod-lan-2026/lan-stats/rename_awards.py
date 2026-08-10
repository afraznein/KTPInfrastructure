#!/usr/bin/env python3
"""Operator-decided award renames, applied over awards.json.

Award titles came from the MySQL-backed script that never landed in this repo,
so a rename has nowhere upstream to live. Keeping them here means the decision
is recorded and re-applies if awards.json is ever regenerated, rather than being
a one-off edit nobody can trace.

    python rename_awards.py           # apply
    python rename_awards.py --check   # exit 1 if any rename is unapplied
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AWARDS = os.path.join(HERE, "awards.json")

# slug -> {title, blurb}; omit a field to leave it alone
RENAMES = {
    "flags-rate": {
        "title": "Touch Grass",
        # the joke only works if the blurb lets it land, so it says the quiet part
        "blurb": "Most flags per half — and he actually does. The Calebsod award.",
    },
    "prone": {
        # was "Sandbagging Like A Boss" — the pun was fine, the 2011 meme was not
        "title": "Carpet Inspector",
        "blurb": "Most time on the deck — someone has to check it. The Milo award.",
    },
}


def apply(awards, dry=False):
    changed = []
    for section in ("decided", "single_match"):
        for a in awards.get(section, []):
            want = RENAMES.get(a.get("slug"))
            if not want:
                continue
            for field, value in want.items():
                if a.get(field) != value:
                    changed.append((a["slug"], field, a.get(field), value))
                    if not dry:
                        a[field] = value
    return changed


def main() -> int:
    awards = json.load(open(AWARDS, encoding="utf-8"))
    known = {a["slug"] for s in ("decided", "single_match") for a in awards.get(s, [])}
    unknown = set(RENAMES) - known
    if unknown:
        sys.exit(f"rename targets not in awards.json: {sorted(unknown)}")

    # Awards created in apply_award_decisions.py carry their title there and it
    # reconciles them on every run, so a rename written here would be undone on
    # the next apply — rename it at its source instead.
    from apply_award_decisions import ADD_AWARD
    authored = {a["slug"] for _, a in ADD_AWARD} & set(RENAMES)
    if authored:
        sys.exit(f"{sorted(authored)} are authored in apply_award_decisions.py — "
                 "rename them there, not here")

    if "--check" in sys.argv:
        pending = apply(awards, dry=True)
        if pending:
            print(f"{len(pending)} rename(s) unapplied — re-run rename_awards.py")
            return 1
        print("award renames are current")
        return 0

    changed = apply(awards)
    if not changed:
        print("no change")
        return 0
    json.dump(awards, open(AWARDS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for slug, field, was, now in changed:
        print(f"  {slug}.{field}: {was!r} -> {now!r}")
    print("\nnow re-embed:  PYTHONHASHSEED=0 python build_ballots.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
