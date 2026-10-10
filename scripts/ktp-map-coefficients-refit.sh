#!/usr/bin/env bash
# Weekly per-map refit -> a pull request nobody is obliged to merge.
#
# Runs on the data server because the fit needs the match database. It never
# writes to main and never merges: a coefficient change is a claim about how a
# map plays, and drew's standing rule (2026-09-28) is that every one of them is
# reviewed. Git history of config/map_coefficients.json is then the record of
# how the maps evolved across the season.
#
# Exit codes: 0 nothing changed or PR opened, 1 the refit itself failed.
set -euo pipefail

REPO="${REPO:-/opt/ktp-reports/KTPInfrastructure}"
BRANCH="map-coefficients/$(date -u +%Y-%m-%d)"
LOG="${LOG:-/var/log/ktp-map-coefficients.log}"

cd "$REPO"
exec >>"$LOG" 2>&1
echo "=== $(date -u +%FT%TZ) refit starting on $(git rev-parse --short HEAD)"

# Refit against main, never against whatever the checkout happens to be on.
git fetch --quiet origin main
git checkout --quiet -B "$BRANCH" origin/main

if python3 -m scripts.fit_map_coefficients --check; then
  echo "table still matches the data; nothing to propose"
  git checkout --quiet -                      # leave the checkout as we found it
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
PROPOSAL="${PROPOSAL:-/var/lib/ktp-map-coefficients}"
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

if git push --quiet origin "$BRANCH" 2>/dev/null; then
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
git checkout --quiet -      # leave the checkout on the branch we found it on
