#!/usr/bin/env bash
# Build ktpamx_i386.so with the Lane B fake-client patch.
#
# Without this binary AMXX cannot see bots at all — every capture path is gated
# on `is_user_connected()`, which returns false for fake clients in extension
# mode — so the whole lane runs blind. It is not optional.
#
# Mirrors KTPInfrastructure/build/amxx/Dockerfile but as a one-off container so
# the whole compose chain is not needed: Ubuntu 22.04 + 32-bit toolchain +
# AMBuild, with HLSDK from a sibling KTPhlsdk checkout.
#
# ## Caching
#
# The build takes ~10 minutes and the ref changes rarely, so a rebuild per
# nightly is almost always wasted. The output is stamped with the commit it was
# built from (`<out>.sha`); a later run with the same commit and the same build
# recipe short-circuits.
#
# The stamp covers the RECIPE as well as the commit — this script's own hash is
# part of it — because changing the toolchain or the configure flags without
# changing KTPAMXX would otherwise silently reuse a stale .so. That is the
# failure mode worth guarding against: a cached artifact that no longer matches
# how it would be built today.
#
# `--force` rebuilds regardless.
#
# ## Configuration
#
# Everything is overridable so the same script runs on a laptop and on a CI
# runner:
#
#   LANEB_WORK    scratch dir for checkouts           (default: $HOME/ktp)
#   LANEB_SRC     KTPAMXX source (path or git URL)    (default: GitHub)
#   LANEB_REF     ref to build                        (default: feat/lane-b-fakeclient-players)
#   LANEB_OUT     where to write ktpamx_i386.so       (default: $HOME/lane-b-out/ktpamx_i386.so)
#   LANEB_DOCKER  docker binary                       (default: docker)
set -euo pipefail

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

W="${LANEB_WORK:-$HOME/ktp}"
SRC="${LANEB_SRC:-https://github.com/afraznein/KTPAMXX.git}"
REF="${LANEB_REF:-feat/lane-b-fakeclient-players}"
OUT="${LANEB_OUT:-$HOME/lane-b-out/ktpamx_i386.so}"
DOCKER="${LANEB_DOCKER:-docker}"
HLSDK_URL="${LANEB_HLSDK_URL:-https://github.com/afraznein/KTPhlsdk.git}"

mkdir -p "$W" "$(dirname "$OUT")"

# ---------------------------------------------------------------------------
# Cache check, before anything expensive.
# ---------------------------------------------------------------------------
recipe_hash() {
    # This script IS the recipe: toolchain image, configure flags, submodule
    # handling. Hashing it means a recipe change invalidates the cache even
    # when the source commit has not moved.
    sha256sum "${BASH_SOURCE[0]}" | cut -c1-12
}

resolve_sha() {
    # The composite action resolves a moving branch once, keys the cache on the
    # resulting commit, then passes that immutable SHA here. `git ls-remote`
    # does not advertise arbitrary object IDs, so accept a full SHA directly;
    # the clone + checkout below still proves the object exists remotely.
    if [[ "$REF" =~ ^[0-9a-fA-F]{40}$ ]]; then
        printf '%s\n' "${REF,,}"
        return
    fi
    if [ -d "$SRC/.git" ] || [ -d "$SRC" ]; then
        git -C "$SRC" rev-parse "$REF" 2>/dev/null && return
    fi
    git ls-remote "$SRC" "$REF" 2>/dev/null | awk '{print $1; exit}'
}

SHA="$(resolve_sha || true)"
if [ -z "$SHA" ]; then
    echo "could not resolve $REF in $SRC" >&2
    exit 1
fi
STAMP="${SHA}-$(recipe_hash)"

if [ "$FORCE" -eq 0 ] && [ -f "$OUT" ] && [ -f "$OUT.sha" ] \
   && [ "$(cat "$OUT.sha")" = "$STAMP" ]; then
    echo "cache hit: $OUT already built from ${SHA:0:12} with this recipe"
    echo "  ($(stat -c%s "$OUT") bytes; pass --force to rebuild)"
    exit 0
fi
echo "cache miss: building ${REF} @ ${SHA:0:12}"

# ---------------------------------------------------------------------------
CHECKOUT="$W/KTPAMXX-laneb"

if [ ! -d "$W/KTPhlsdk/.git" ]; then
    echo "cloning KTPhlsdk..."
    git clone -q "$HLSDK_URL" "$W/KTPhlsdk"
fi

# Clone the branch rather than copying a working tree: support/Versioning reads
# .git/HEAD at configure time, and building from the commit is the same
# discipline the artifact builder uses.
#
# A prior build ran as root in the container and left root-owned files behind
# (obj-linux/, support/ambuild/), which an unprivileged user cannot delete.
# Remove them the same way they were created rather than reaching for sudo.
if [ -d "$CHECKOUT" ]; then
    "$DOCKER" run --rm -v "$W:/w" alpine:latest rm -rf /w/KTPAMXX-laneb || true
fi
rm -rf "$CHECKOUT"
git clone -q --no-single-branch "$SRC" "$CHECKOUT"
git -C "$CHECKOUT" checkout -q "$SHA"
# public/amtl is a submodule (alliedmodders/amtl) and is not populated by a
# plain clone, so the build runs until MemoryUtils.cpp and dies on a missing
# amtl/am-vector.h.
git -C "$CHECKOUT" submodule update --init --recursive -q

echo "building from $(git -C "$CHECKOUT" rev-parse --short HEAD)"
echo "amtl headers: $(ls "$CHECKOUT/public/amtl/amtl" 2>/dev/null | wc -l)"
hits=$(grep -c KTP_LANE_B_FAKECLIENTS "$CHECKOUT/amxmodx/meta_api.cpp" || true)
if [ "$hits" -eq 0 ]; then
    echo "KTP_LANE_B_FAKECLIENTS is not in meta_api.cpp at $REF — this build" >&2
    echo "would produce a stock binary and the lane would silently run blind." >&2
    exit 1
fi
echo "define present in source: $hits hit(s)"

if ! "$DOCKER" image inspect ktp-amxx-builder:laneb >/dev/null 2>&1; then
    echo "building builder image..."
    "$DOCKER" build -t ktp-amxx-builder:laneb -f - /tmp <<'EOF'
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
RUN dpkg --add-architecture i386 && apt-get update && apt-get install -y --no-install-recommends \
      build-essential g++-multilib gcc-multilib cmake make nasm \
      python3 python3-pip python3-venv git wget curl unzip \
      lib32z1-dev libc6-dev-i386 linux-libc-dev:i386 \
      autoconf automake libtool pkg-config ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/alliedmodders/ambuild /opt/ambuild \
 && python3 -m venv /opt/ambuild-venv \
 && . /opt/ambuild-venv/bin/activate && pip install -q --upgrade pip && pip install -q /opt/ambuild
EOF
fi

"$DOCKER" run --rm \
    -v "$CHECKOUT:/build/KTPAMXX" \
    -v "$W/KTPhlsdk:/build/KTPhlsdk:ro" \
    -e HLSDK=/build/KTPhlsdk \
    -e KTP_LANE_B_FAKECLIENTS=1 \
    -w /build/KTPAMXX ktp-amxx-builder:laneb bash -c '
        set -e
        # support/generate_headers.py shells out to git for the version header,
        # and the bind-mounted repo is owned by the host user while this runs as
        # root. Same waiver as the Lane B image, same reasoning: throwaway
        # container, nothing to protect.
        git config --global --add safe.directory "*"
        rm -rf support/ambuild && cp -r /opt/ambuild support/ambuild
        find . -name "*.sh" -exec sed -i "s/\r$//" {} \;
        . /opt/ambuild-venv/bin/activate
        python3 configure.py --enable-optimize --no-mysql --no-plugins
        cd obj-linux && python3 $(which ambuild)
    ' 2>&1 | tail -25

BUILT="$(find "$CHECKOUT/obj-linux" -name 'ktpamx_i386.so' | head -1)"
if [ -z "$BUILT" ]; then
    echo "build produced no ktpamx_i386.so" >&2
    exit 1
fi

cp "$BUILT" "$OUT"
# Stamp last, and only on success: a stamp written next to a failed or partial
# copy would make every later run a false cache hit.
echo "$STAMP" > "$OUT.sha"
echo
echo "wrote $OUT ($(stat -c%s "$OUT") bytes) from ${SHA:0:12}"
