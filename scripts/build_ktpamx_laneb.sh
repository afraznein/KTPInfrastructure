#!/usr/bin/env bash
# Build ktpamx_i386.so with the Lane B fake-client patch.
#
# Mirrors KTPInfrastructure/build/amxx/Dockerfile but as a one-off container so
# the whole compose chain is not needed: Ubuntu 22.04 + 32-bit toolchain +
# AMBuild, with HLSDK from a sibling KTPhlsdk checkout.
set -euo pipefail

W=/home/drewk/ktp
cd "$W"

if [ ! -d "$W/KTPhlsdk/.git" ]; then
    echo "cloning KTPhlsdk..."
    git clone -q https://github.com/afraznein/KTPhlsdk.git "$W/KTPhlsdk"
fi

# Clone the branch rather than copying the working tree: support/Versioning
# reads .git/HEAD at configure time, and building from the commit is the same
# discipline the artifact builder uses.
# A prior build ran as root in the container and left root-owned files behind
# (obj-linux/, support/ambuild/), which this unprivileged user cannot delete.
# Remove them the same way they were created rather than reaching for sudo.
if [ -d "$W/KTPAMXX-laneb" ]; then
    /home/drewk/bin/dk run --rm -v "$W:/w" alpine:latest rm -rf /w/KTPAMXX-laneb || true
fi
rm -rf "$W/KTPAMXX-laneb"
git clone -q --no-single-branch /mnt/g/GIT/ktp_stats/branches/KTPAMXX "$W/KTPAMXX-laneb"
git -C "$W/KTPAMXX-laneb" checkout -q feat/lane-b-fakeclient-players
# public/amtl is a submodule (alliedmodders/amtl) and is not populated in the
# source checkout, so a plain clone builds until MemoryUtils.cpp then dies on a
# missing amtl/am-vector.h.
git -C "$W/KTPAMXX-laneb" submodule update --init --recursive -q
echo "building from $(git -C "$W/KTPAMXX-laneb" rev-parse --short HEAD)"
echo "amtl headers: $(ls "$W/KTPAMXX-laneb/public/amtl/amtl" 2>/dev/null | wc -l)"
echo "define present in source: $(grep -c KTP_LANE_B_FAKECLIENTS "$W/KTPAMXX-laneb/amxmodx/meta_api.cpp") hit(s)"

if ! /home/drewk/bin/dk image inspect ktp-amxx-builder:laneb >/dev/null 2>&1; then
    echo "building builder image..."
    /home/drewk/bin/dk build -t ktp-amxx-builder:laneb -f - /tmp <<'EOF'
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

/home/drewk/bin/dk run --rm \
    -v "$W/KTPAMXX-laneb:/build/KTPAMXX" \
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

echo
echo "=== ktpamx artifacts ==="
find "$W/KTPAMXX-laneb/obj-linux" -name "ktpamx*.so" -o -name "amxmodx_mm*.so" 2>/dev/null | head
