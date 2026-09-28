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
git push --quiet origin "$BRANCH"

gh pr create --base main --head "$BRANCH" \
  --title "map coefficients: weekly refit $(date -u +%Y-%m-%d)" \
  --body "$(python3 -m scripts.fit_map_coefficients --check 2>&1 || true)

Automated weekly refit. Review the diff in \`config/map_coefficients.json\`:
each changed line says a map plays differently than we currently believe.
Merging accepts the new numbers; closing leaves the table as it is.

Coordination-Workstream: infra-hidden-value-plays"
echo "pull request opened from $BRANCH"
