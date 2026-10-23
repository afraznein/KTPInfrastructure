#!/usr/bin/env bash
# Publish files from the data server into the PRIVATE coordination repo
# (andsmit9/ktp-coordination), so a report that names players can be read on GitHub
# by the three people with access and nowhere else. KTPInfrastructure is public;
# nothing like this is ever committed there.
#
# Usage: ktp-coord-publish.sh <subdir-in-repo> <file>...
#   Copies each file into <subdir> (same basename), commits by path, pushes to main.
#   A new dated file per night never conflicts; `latest.md` is overwritten in place.
#
# Auth: one WRITE deploy key scoped to that one repo, private half at
# $KTP_COORD_KEY (default /etc/ktp/coordination-deploy.key, mode 600 root).
# Distinct from the read-only COORD_DEPLOY_KEY the CI check uses.
#
# Exit codes, on purpose:
#   0  published, or nothing new, or NO KEY INSTALLED (printed loudly -- until the key
#      lands this is the configured state, not a fault; a nightly red embed for a known
#      gap would train everyone to ignore the embed)
#   1  the key exists and the clone/commit/push still failed -- that is a fault
set -euo pipefail

subdir=${1:?subdir in the coordination repo}; shift
[ $# -ge 1 ] || { echo "ktp-coord-publish: no files given" >&2; exit 1; }
repo=${KTP_COORD_REPO:-git@github.com:andsmit9/ktp-coordination.git}
key=${KTP_COORD_KEY:-/etc/ktp/coordination-deploy.key}
clone=${KTP_COORD_CLONE:-${STATE_DIRECTORY:-/var/lib/ktp-coord-publish}/coordination}

if [ ! -r "$key" ]; then
  echo "ktp-coord-publish: NOT PUBLISHED -- no deploy key at $key (files stay local: $*)" >&2
  exit 0
fi
export GIT_SSH_COMMAND="ssh -i $key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
g() { git -C "$clone" -c user.name="ktp-data-server" -c user.email="ktp-data-server@ktpdod.com" "$@"; }

if [ ! -d "$clone/.git" ]; then
  mkdir -p "$(dirname "$clone")"
  git clone -q --depth 1 --branch main "$repo" "$clone"
fi
g fetch -q --depth 1 origin main
g reset -q --hard origin/main

mkdir -p "$clone/$subdir"
cp -- "$@" "$clone/$subdir/"
g add -- "$subdir"
if g diff --cached --quiet; then
  echo "ktp-coord-publish: nothing new under $subdir"
  exit 0
fi
g commit -q -m "$(basename "$subdir"): publish $(date +%F) from the data server" -- "$subdir"

# Other writers (the hourly stats bot, people) push to main too; a new file rebases clean.
for attempt in 1 2 3; do
  if g push -q origin HEAD:main; then
    echo "ktp-coord-publish: pushed $(g rev-parse --short HEAD) -> $subdir ($#$([ $# -eq 1 ] && echo ' file' || echo ' files'))"
    exit 0
  fi
  g fetch -q --depth 1 origin main
  g rebase -q origin/main || { g rebase --abort; break; }
done
echo "ktp-coord-publish: push to $repo failed after $attempt attempt(s)" >&2
exit 1
