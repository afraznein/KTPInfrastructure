#!/usr/bin/env bash
# Pre-push hook for KTPInfrastructure.
#
# Runs a full `make build` in Docker before allowing a push. Breaks are
# expensive in production (plugins load on real servers), and the build
# catches most regressions — compile errors, missing includes, extension-mode
# violations, template drift, Dockerfile breakage.
#
# Install with: scripts/install-hooks.sh
# Bypass once  : git push --no-verify
# Disable      : export KTP_SKIP_PREPUSH=1
set -euo pipefail

if [[ "${KTP_SKIP_PREPUSH:-0}" == "1" ]]; then
  echo "[pre-push] KTP_SKIP_PREPUSH=1 — skipping build"
  exit 0
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

VERSION="prepush-$(date +%Y%m%d-%H%M%S)"

echo "[pre-push] make build VERSION=$VERSION"
echo "[pre-push] (bypass with --no-verify or KTP_SKIP_PREPUSH=1)"

if ! make build VERSION="$VERSION"; then
  echo
  echo "[pre-push] BUILD FAILED — push aborted."
  echo "[pre-push] Fix the build, or bypass with: git push --no-verify"
  exit 1
fi

echo "[pre-push] build OK (artifacts: artifacts/$VERSION/)"
