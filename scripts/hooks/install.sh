#!/bin/bash
# Install the KTP git hooks into this clone.
#
# Hooks do not travel with a clone, so this is opt-in per checkout -- which is
# itself a rot mode: a fresh clone is unprotected until someone runs this. The
# CI gate is the backstop that does not depend on anyone remembering.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK_DIR="$(git rev-parse --git-path hooks)"
mkdir -p "${HOOK_DIR}"

for hook in pre-push; do
  src="${REPO_ROOT}/scripts/hooks/${hook}"
  dest="${HOOK_DIR}/${hook}"
  if [ -e "${dest}" ] && ! grep -q "KTP pre-push secret gate" "${dest}" 2>/dev/null; then
    echo "refusing to overwrite existing ${dest} -- merge it by hand" >&2
    exit 1
  fi
  install -m 0755 "${src}" "${dest}"
  echo "installed ${dest}"
done

echo
echo "Verify with:  python scripts/ktp_secret_scan.py selftest"
