#!/usr/bin/env bash
# Weekly per-map refit -> a pull request nobody is obliged to merge.
#
# Runs on the data server because the fit needs the match database. It never
# writes to main and never merges: a coefficient change is a claim about how a
# map plays, and drew's standing rule (2026-09-28) is that every one of them is
# reviewed. Git history of config/map_coefficients.json is then the record of
# how the maps evolved across the season.
#
# ⛔ THE REFIT RUNS IN ITS OWN WORKTREE AND NEVER MOVES $REPO, AND AN EARLIER
# VERSION DID. That version ran `git checkout -B map-coefficients/<date>` in
# $REPO itself and changed back on only two of its paths -- the clean-exit line
# and the last line. With `set -e` every step between them exits immediately, so
# a failed fit, a failed commit, a full disk under format-patch or any unreadable
# path left the checkout parked on a dated branch, and nothing said so. $REPO is
# SERVING -- report jobs read it -- so even the success path served a dated
# branch for the length of the fit.
#
# A trap would have closed the failure half and not the other half, because
# moving a serving checkout at all is the defect. So the move is gone instead:
# `git worktree add` gets a tree of its own off origin/main, $REPO keeps whatever
# ref it was on, and the trap below only removes that scratch tree.
#
# Exit codes: 0 nothing changed or PR opened, 1 the refit itself failed.
set -euo pipefail

REPO="${REPO:-/opt/ktp-reports/KTPInfrastructure}"
BRANCH="map-coefficients/$(date -u +%Y-%m-%d)"
# Inside LogsDirectory=ktp-map-coefficients, which systemd creates owned by
# User= on every start. ⛔ NOT a bare file in /var/log: that directory is
# 775 root:syslog and ktpreports cannot create one there, so the old default
# made the job fail on its first line.
LOG="${LOG:-/var/log/ktp-map-coefficients/refit.log}"
PROPOSAL="${PROPOSAL:-/var/lib/ktp-map-coefficients}"
# Fixed rather than mktemp: a crashed run leaves a registration behind, and a
# fixed path is one the next run can find and clear. ⛔ Never a glob -- this repo
# has other registered worktrees and a sweep would unregister them.
WORKTREE="${WORKTREE:-/var/lib/ktp-map-coefficients/.refit-worktree}"

cd "$REPO"
exec >>"$LOG" 2>&1
echo "=== $(date -u +%FT%TZ) refit starting; $REPO is on $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD) and stays there"

# Refit against main, never against whatever the checkout happens to be on.
git fetch --quiet origin main

drop_worktree() {
  # Only ever this one path. Errors are swallowed because cleanup must not turn a
  # finished refit into a failure, and `prune` is what makes a crashed previous
  # run self-healing instead of permanently blocking the next one.
  git -C "$REPO" worktree remove --force "$WORKTREE" 2>/dev/null || true
  rm -rf "$WORKTREE" 2>/dev/null || true
  git -C "$REPO" worktree prune 2>/dev/null || true
}

drop_worktree                   # clear a leftover from a crashed run
trap drop_worktree EXIT
mkdir -p "$(dirname "$WORKTREE")"

# --detach so no local branch is created in $REPO's refs either: a failed run
# leaves no dated branch behind to be mistaken for work in progress. The push
# names the remote branch explicitly instead.
git worktree add --quiet --detach "$WORKTREE" origin/main
cd "$WORKTREE"
echo "refitting in $WORKTREE at $(git rev-parse --short HEAD)"

if python3 -m scripts.fit_map_coefficients --check; then
  echo "table still matches the data; nothing to propose"
  exit 0
fi

python3 -m scripts.fit_map_coefficients --write
git add config/map_coefficients.json
git commit --quiet -m "map coefficients: weekly refit $(date -u +%Y-%m-%d)

Proposed by ktp-map-coefficients.timer. The diff is the review: each line is
a claim that a map now plays differently than the committed table says.
Merging accepts it; closing rejects it and the table stands."

# PUSHING IS OPTIONAL. This host holds a read-only deploy key -- it pulls, it
# does not push -- so requiring an authenticated `gh` made the install wait on a
# credential decision nobody needed to take. If push and PR work, they happen;
# otherwise the refit has still produced everything a human needs and says where
# it is. The review requirement is A DIFF SOMEONE READS, not a pull request.
mkdir -p "$PROPOSAL"
git format-patch --quiet -1 -o "$PROPOSAL" HEAD
cp config/map_coefficients.json "$PROPOSAL/map_coefficients.proposed.json"
python3 -m scripts.fit_map_coefficients --check > "$PROPOSAL/diff.txt" 2>&1 || true

# The body is the diff plus the trailer the coordination gate requires. Without
# `Coordination-Workstream` the check fails, so an auto-opened PR would have
# gone red every week over a missing line.
cp "$PROPOSAL/diff.txt" "$PROPOSAL/body.md"
echo ""                                                            >> "$PROPOSAL/body.md"
echo "Automated weekly refit. Each changed line says a map plays"  >> "$PROPOSAL/body.md"
echo "differently than the committed table believes. Merging"      >> "$PROPOSAL/body.md"
echo "accepts the new numbers; closing leaves the table as it is." >> "$PROPOSAL/body.md"
echo ""                                                            >> "$PROPOSAL/body.md"
echo "Coordination-Workstream: infra-hidden-value-plays"           >> "$PROPOSAL/body.md"

# HEAD:refs/heads/<branch> -- the commit sits on a detached HEAD, so name the
# remote branch rather than relying on a local one existing.
if git push --quiet origin "HEAD:refs/heads/$BRANCH" 2>/dev/null; then
  if gh pr create --base main --head "$BRANCH" \
       --title "map coefficients: weekly refit $(date -u +%Y-%m-%d)" \
       --body-file "$PROPOSAL/body.md" 2>/dev/null; then
    echo "pull request opened from $BRANCH"
  else
    echo "pushed $BRANCH but could not open a PR -- open one from that branch"
  fi
else
  echo "no push rights, which is expected on this host: the proposal is in $PROPOSAL"
  echo "  map_coefficients.proposed.json   the new table"
  echo "  diff.txt                         what moved"
  echo "  body.md                          a ready PR body, trailer included"
  echo "  0001-*.patch                     apply elsewhere with: git am"
  echo "Nothing was pushed and nothing was merged. The table on main stands"
  echo "until a human takes this to a pull request."
fi
