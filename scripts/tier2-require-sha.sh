#!/usr/bin/env bash
# Usage: tier2-require-sha.sh <source-checkout> <expected-40-hex-sha>
#
# Gate for a Tier-2 build: the checkout it compiles must be exactly the pinned
# commit, clean. Prints the short SHA to bake into the artifact on success;
# exits non-zero with a ::error:: line on anything else, including when HEAD
# cannot be resolved -- an artifact that cannot name its source certifies nothing.
set -euo pipefail

src="${1:-}"
want="${2:-}"

fail() { echo "::error::tier2-require-sha: $*" >&2; exit 1; }

[ -n "$src" ] || fail "no source checkout given"
# A branch or short name would let the build follow whatever it resolves to today.
[[ "$want" =~ ^[0-9a-f]{40}$ ]] || fail "expected SHA must be a full 40-hex commit, got '${want}'"

got="$(git -C "$src" rev-parse --verify --quiet 'HEAD^{commit}')" \
  || fail "cannot resolve HEAD in '$src'"
[ "$got" = "$want" ] || fail "'$src' is at $got, not the pinned $want"

# `status` failing must not read as clean.
dirty="$(git -C "$src" status --porcelain)" || fail "cannot read status of '$src'"
[ -z "$dirty" ] || fail "'$src' has uncommitted changes; refusing to certify a build of it"

git -C "$src" rev-parse --short "$got"
