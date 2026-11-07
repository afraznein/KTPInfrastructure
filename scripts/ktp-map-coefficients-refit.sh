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
# ⛔ AND EXACTLY ONE PATCH IS APPLICABLE AT A TIME, BECAUSE FOR FOUR WEEKS
# THREE WERE. `git format-patch` names its output after the commit subject, so
# every run left its own dated patch behind, while diff.txt, body.md and the
# proposed table are fixed names each run overwrote. By 2026-11-02 the
# directory held four dated patches beside one undated diff describing only the
# newest -- and checked against origin/main that day, THREE of the four still
# applied cleanly. A reviewer who read the diff and applied the first patch
# they saw shipped a different week's refit, with no error anywhere.
#
# Documenting that would only have made the wrong act detectable. So a run now
# moves the previous set into superseded/ BEFORE writing its own, asserts that
# format-patch left exactly one patch, and writes a MANIFEST.md naming it.
# Moved rather than deleted: the commit a patch came from lived in the scratch
# worktree the EXIT trap removes, so the patch file is the only copy of it.
#
# Exit codes: 0 nothing changed or PR opened, 1 the refit itself failed.
set -euo pipefail

REPO="${REPO:-/opt/ktp-reports/KTPInfrastructure}"
# ONE date for the branch, the commit subject, the patch filename that comes
# from that subject, and the manifest. Read separately they can disagree across
# a UTC midnight. Not reachable at the installed schedule (Mon 14:00 UTC under
# a 3h cap), but a run whose artifacts name two different days is exactly the
# ambiguity the rest of this script now exists to prevent.
RUN_DATE="$(date -u +%Y-%m-%d)"
BRANCH="map-coefficients/$RUN_DATE"
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

# Everything a previous run produced, moved aside under one named directory, so
# the top level of $PROPOSAL only ever holds the run in progress. A nested
# superseded/ copy cannot be reached by `git am $PROPOSAL/*.patch`, which is
# what makes the wrong act impossible rather than merely visible.
supersede_previous() {
  local stamp dest f
  stamp="$(date -u +%Y-%m-%dT%H%M%SZ)"
  dest="$PROPOSAL/superseded/before-$stamp"
  local -a old=()
  for f in "$PROPOSAL"/0001-*.patch \
           "$PROPOSAL/diff.txt" \
           "$PROPOSAL/body.md" \
           "$PROPOSAL/map_coefficients.proposed.json" \
           "$PROPOSAL/MANIFEST.md"; do
    # An if, not `[ -e ] && old+=()`: under `set -e` a failing AND-list as the
    # last command of the loop body ends the run.
    if [ -e "$f" ]; then old+=("$f"); fi
  done
  if [ "${#old[@]}" -eq 0 ]; then
    echo "no previous proposal to supersede"
    return 0
  fi
  mkdir -p "$dest"
  mv -- "${old[@]}" "$dest/"
  echo "moved ${#old[@]} artifact(s) from previous run(s) -> $dest"
}

drop_worktree                   # clear a leftover from a crashed run
trap drop_worktree EXIT
mkdir -p "$(dirname "$WORKTREE")"

# --detach so no local branch is created in $REPO's refs either: a failed run
# leaves no dated branch behind to be mistaken for work in progress. The push
# names the remote branch explicitly instead.
git worktree add --quiet --detach "$WORKTREE" origin/main
cd "$WORKTREE"
BASE="$(git rev-parse HEAD)"
echo "refitting in $WORKTREE at $(git rev-parse --short "$BASE")"

# ONE fit per run; it was three until 2026-10-14 -- --check to decide, --write to
# produce, --check again to render the diff -- and each one reloads the whole
# corpus at ~64 min a pass, so three exceeded TimeoutStartSec=3h and the diff a
# reviewer read need not have described the table being committed.
mkdir -p "$PROPOSAL"
# BEFORE the fit writes diff.txt, so no moment exists in which a new diff sits
# beside an old patch. A fit that then fails leaves no patch at all, which is
# unambiguous, and the previous complete set is intact one directory down.
supersede_previous
python3 -m scripts.fit_map_coefficients --write | tee "$PROPOSAL/diff.txt"

# --write leaves the file untouched when no coefficient moved, so this is the
# whole "is there anything to propose" test -- and `fitted_at` moving on every
# run is why it could not be asked of the file before.
if git diff --quiet -- config/map_coefficients.json; then
  echo "table still matches the data; nothing to propose"
  exit 0
fi

# GET THE FIT OUT BEFORE ANY GIT STEP: the EXIT trap removes $WORKTREE whether
# the run succeeded or not, and on 2026-10-14 a commit that failed for a
# five-second reason took an hour of fitting with it.
cp config/map_coefficients.json "$PROPOSAL/map_coefficients.proposed.json"

git add config/map_coefficients.json
# -c rather than a gitconfig on the box: ktpreports is a nologin account with no
# home directory, so `git commit` exited 128 "Author identity unknown" and every
# run died here. Same pattern as .github/workflows/mmr-weekly.yml.
git -c user.name="ktp-map-coefficients-bot" -c user.email="noreply@github.com" commit --quiet -m "map coefficients: weekly refit $RUN_DATE

Proposed by ktp-map-coefficients.timer. The diff is the review: each line is
a claim that a map now plays differently than the committed table says.
Merging accepts it; closing rejects it and the table stands."

# PUSHING IS OPTIONAL. This host holds a read-only deploy key -- it pulls, it
# does not push -- so requiring an authenticated `gh` made the install wait on a
# credential decision nobody needed to take. If push and PR work, they happen;
# otherwise the refit has still produced everything a human needs and says where
# it is. The review requirement is A DIFF SOMEONE READS, not a pull request.
git format-patch --quiet -1 -o "$PROPOSAL" HEAD

# ASSERTED, NOT ASSUMED. The supersede pass above is the reason this is 1, so a
# surprise here has to stop the run rather than reach a reviewer as a choice.
PATCHES=()
for f in "$PROPOSAL"/0001-*.patch; do
  if [ -e "$f" ]; then PATCHES+=("$(basename "$f")"); fi
done
if [ "${#PATCHES[@]}" -ne 1 ]; then
  echo "expected exactly one patch in $PROPOSAL, found ${#PATCHES[@]}"
  exit 1
fi
PATCH="${PATCHES[0]}"

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

# Written LAST, so it only ever describes a set that is already complete. This
# is what ties the diff a human reads to the patch they apply -- for four weeks
# those were different runs.
cat > "$PROPOSAL/MANIFEST.md" <<EOF
# map coefficients refit -- $RUN_DATE

Every file at the top level of this directory belongs to this one run. Earlier
runs are under \`superseded/\`, where nothing in them can be applied by mistake.

- \`$PATCH\` -- the only applicable patch: \`git am $PATCH\`
- \`diff.txt\` -- what moved, as the fitter printed it
- \`body.md\` -- diff.txt plus a PR body and the coordination trailer
- \`map_coefficients.proposed.json\` -- the proposed table in full

Fitted from origin/main at $BASE. Nothing was merged and nothing was pushed by
this file: the table on main stands until a human takes it to a pull request.
EOF

# HEAD:refs/heads/<branch> -- the commit sits on a detached HEAD, so name the
# remote branch rather than relying on a local one existing.
if git push --quiet origin "HEAD:refs/heads/$BRANCH" 2>/dev/null; then
  if gh pr create --base main --head "$BRANCH" \
       --title "map coefficients: weekly refit $RUN_DATE" \
       --body-file "$PROPOSAL/body.md" 2>/dev/null; then
    echo "pull request opened from $BRANCH"
  else
    echo "pushed $BRANCH but could not open a PR -- open one from that branch"
  fi
else
  echo "no push rights, which is expected on this host: the proposal is in $PROPOSAL"
  echo "  MANIFEST.md                      what belongs to this run"
  echo "  map_coefficients.proposed.json   the new table"
  echo "  diff.txt                         what moved"
  echo "  body.md                          a ready PR body, trailer included"
  echo "  $PATCH"
  echo "    the ONLY applicable patch; earlier runs are under superseded/"
  echo "Nothing was pushed and nothing was merged. The table on main stands"
  echo "until a human takes this to a pull request."
fi
