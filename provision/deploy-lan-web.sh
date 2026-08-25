#!/usr/bin/env bash
# deploy-lan-web — push sites/lan-web/app to /opt/lan-web/app, deliberately.
#
# /opt/lan-web was hand-managed from June to August 2026: no deploy script, no
# drift check, 19 .deploy-bak-* directories (85 MB) as the fossil record. Two
# things went wrong in that window and both are the reason this script exists:
# the box ran a bracket.py whose fix had been on main for five days, and a
# warmup panel lived only on the box where the first rsync would have deleted
# it.
#
# So this is a deliberate deploy with a pre-flight, matching the house pattern
# (stage-wave.py, deploy-to-fleet.py, the .new + nightly-swap path) rather than
# a git pull that changes live code the moment someone commits.
#
#   ./deploy-lan-web.sh              # dry run, shows what would change
#   ./deploy-lan-web.sh --apply      # do it
#
# Needs rsync, ssh and python3, so run it from WSL or the data server — not
# from Git Bash on Windows, which has none of the three.
#
# Refuses to run if the drift check reports BOX-ONLY files: --delete would
# destroy them, and "it was only on the server" is exactly how the warmup panel
# nearly went. Commit them first, or pass --force-delete-box-only if you mean it.
#
# That guard is only worth what the check can see, and it once saw seven file
# suffixes while --delete saw everything. Both now read the same
# provision/lan-web-sync.exclude, so what survives a deploy and what the
# pre-flight inspects are the same set by construction.
#
# It also refuses --apply when the source tree is not the reviewed one. SRC is a
# working tree, so without this the branch someone happened to have checked out
# decides what production runs -- and the drift check, reading the same tree,
# would call the result "in sync" afterwards. Override with
# --force-unreviewed-source, or point LAN_WEB_BASE_REF somewhere else.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/sites/lan-web/app/"
SRC_REL="sites/lan-web/app"
BASE_REF="${LAN_WEB_BASE_REF:-origin/main}"
HOST="${DATA_SSH_HOST:-74.91.112.242}"
USER="${DATA_SSH_USER:-root}"
DST="/opt/lan-web/app/"
UNIT="lan-web"
STAMP="$(date +%Y%m%d-%H%M%S)"

APPLY=0
FORCE=0
FORCE_SRC=0
for arg in "$@"; do
  case "$arg" in
    --apply)                     APPLY=1 ;;
    --force-delete-box-only)     FORCE=1 ;;
    --force-unreviewed-source)   FORCE_SRC=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

[ -d "$SRC" ] || { echo "source tree missing: $SRC" >&2; exit 2; }

# The one exclude list, read by rsync here and by the drift check when it
# decides what to look at. Two copies of this list is how the guard goes blind
# to something --delete still deletes.
EXCLUDES="$REPO_ROOT/provision/lan-web-sync.exclude"
[ -f "$EXCLUDES" ] || { echo "exclude list missing: $EXCLUDES" >&2; exit 2; }

echo "== pre-flight: drift check =="
set +e
DRIFT="$(python3 "$REPO_ROOT/scripts/ktp-lan-web-drift.py" 2>&1)"; DRIFT_RC=$?
set -e
echo "$DRIFT"

# 0 in sync, 1 drift with nothing box-only, 3 box-only present. Anything else --
# 2 from the checker, 127 from a missing python3, 1 from a traceback that never
# reached the comparison -- means we did not learn whether the box has box-only
# files, and proceeding would --delete on the strength of a question that was
# never asked.
case "$DRIFT_RC" in
  0|1|3) ;;
  *) echo >&2
     echo "drift check did not run (exit $DRIFT_RC) — refusing to deploy blind." >&2
     exit 2 ;;
esac

# The exit code and the report have to tell the same story. They are derived
# from the same comparison, so a disagreement means the checker is not the
# program we think it is -- which is exactly the state this guard failed in
# before, and the state where a green answer is worth nothing.
SAYS_BOX_ONLY=0
# A here-string, not a pipe: under pipefail a `grep -q` that matches can leave
# the writer with SIGPIPE and turn a match into a nonzero pipeline.
if grep -q '^BOX-ONLY' <<< "$DRIFT"; then SAYS_BOX_ONLY=1; fi
if { [ "$DRIFT_RC" -eq 3 ] && [ "$SAYS_BOX_ONLY" -ne 1 ]; } ||
   { [ "$DRIFT_RC" -ne 3 ] && [ "$SAYS_BOX_ONLY" -eq 1 ]; }; then
  echo >&2
  echo "drift check disagrees with itself (exit $DRIFT_RC, report says box-only=$SAYS_BOX_ONLY)" >&2
  echo "— refusing to deploy on an answer that is not self-consistent." >&2
  exit 2
fi

if [ "$DRIFT_RC" -eq 3 ] && [ "$FORCE" -ne 1 ]; then
  echo >&2
  echo "REFUSING: files exist only on the box and --delete would destroy them." >&2
  echo "Commit them, or re-run with --force-delete-box-only." >&2
  exit 1
fi

# Only --apply is gated: a dry run showing an unreviewed tree is information,
# not a deploy. An unresolvable BASE_REF is refused rather than skipped -- a
# guard that cannot run must not read as one that passed.
if [ "$APPLY" -eq 1 ] && [ "$FORCE_SRC" -ne 1 ]; then
  echo
  echo "== pre-flight: source is the reviewed tree =="
  if ! git -C "$REPO_ROOT" rev-parse --verify --quiet "$BASE_REF^{commit}" >/dev/null; then
    echo "cannot resolve $BASE_REF (fetch first, or set LAN_WEB_BASE_REF)" >&2
    echo "— refusing to deploy a tree of unknown provenance." >&2
    exit 2
  fi
  if git -C "$REPO_ROOT" diff --quiet "$BASE_REF" -- "$SRC_REL"; then
    echo "$SRC_REL matches $BASE_REF"
  else
    echo >&2
    echo "REFUSING: $SRC_REL differs from $BASE_REF — this would deploy an" >&2
    echo "unreviewed tree, and the post-deploy drift check would then call it" >&2
    echo "\"in sync\". Merge it first, or re-run with --force-unreviewed-source." >&2
    git -C "$REPO_ROOT" diff --stat "$BASE_REF" -- "$SRC_REL" >&2
    exit 1
  fi
fi

RSYNC_ARGS=(-rlpt --delete --itemize-changes --exclude-from "$EXCLUDES")

if [ "$APPLY" -ne 1 ]; then
  echo
  echo "== DRY RUN — what would change =="
  rsync "${RSYNC_ARGS[@]}" --dry-run "$SRC" "$USER@$HOST:$DST"
  echo
  echo "(nothing was changed; re-run with --apply)"
  exit 0
fi

echo
echo "== backup (a tarball, not another .deploy-bak- directory) =="
ssh "$USER@$HOST" "tar czf /root/lan-web-app-$STAMP.tgz -C /opt/lan-web app \
  && ls -l /root/lan-web-app-$STAMP.tgz"

echo
echo "== deploy =="
rsync "${RSYNC_ARGS[@]}" "$SRC" "$USER@$HOST:$DST"
ssh "$USER@$HOST" "chown -R lanweb:lanweb /opt/lan-web/app && \
  find /opt/lan-web/app -type f -exec chmod 644 {} + && \
  find /opt/lan-web/app -type d -exec chmod 755 {} +"

echo
echo "== restart =="
ssh "$USER@$HOST" "systemctl restart $UNIT && sleep 3 && systemctl is-active $UNIT"

echo
echo "== verify: serving, and in sync =="
ssh "$USER@$HOST" "curl -sS -o /dev/null -w 'lan-web http %{http_code}\n' http://127.0.0.1:8099/"
set +e
python3 "$REPO_ROOT/scripts/ktp-lan-web-drift.py"; VERIFY_RC=$?
set -e
# The deploy already happened; a nonzero here is a report, not a reason to die
# under set -e with no explanation of which of the four answers it was.
case "$VERIFY_RC" in
  0) echo "post-deploy: in sync" ;;
  1) echo "post-deploy: drift remains (nothing box-only) — see above" >&2 ;;
  3) echo "post-deploy: BOX-ONLY files remain — see above" >&2 ;;
  *) echo "post-deploy: drift check did not run (exit $VERIFY_RC)" >&2 ;;
esac
exit "$VERIFY_RC"
