#!/bin/bash
# package-fastdl-bundle.sh — produce a portable FastDL game-files bundle.
#
# Run this on the production data server (74.91.112.242) to capture the
# /var/www/fastdl/dod/ tree (maps, sprites, sound, models, etc) that
# clients pull when joining the game. Resulting tarball is suitable for
# FASTDL_FILES_PATH in a LAN deployment.
#
# Note on size: a full FastDL tree is typically a few hundred MB. If the
# LAN box has bandwidth-constrained transfer, you can prune to just the
# maps the rotation actually uses with --maps-only.
#
# Usage:
#   sudo ./package-fastdl-bundle.sh [--maps-only] [output-tarball]
# Default output: /tmp/fastdl-bundle-<YYYYMMDD>.tar.gz
#
# Restore on the LAN box:
#   mkdir -p /tmp/fastdl-staging
#   tar -xzf fastdl-bundle-*.tar.gz -C /tmp/fastdl-staging
#   # then in lan-deploy.conf: FASTDL_FILES_PATH="/tmp/fastdl-staging"

set -eu -o pipefail

SRC_DIR=/var/www/fastdl/dod
MAPS_ONLY=0
OUT=""

while [ $# -gt 0 ]; do
    case "$1" in
        --maps-only) MAPS_ONLY=1; shift ;;
        -h|--help)   sed -n '1,/^$/p' "$0" | grep '^# '; exit 0 ;;
        *)           OUT="$1"; shift ;;
    esac
done

[ -z "$OUT" ] && OUT=/tmp/fastdl-bundle-$(date +%Y%m%d).tar.gz

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: run as root (need read access to $SRC_DIR/)" >&2
    exit 1
fi

if [ ! -d "$SRC_DIR" ]; then
    echo "ERROR: $SRC_DIR does not exist — is this the data server?" >&2
    exit 1
fi

echo "Packaging FastDL bundle from $SRC_DIR ..."
echo "  Output:    $OUT"
if [ "$MAPS_ONLY" = 1 ]; then
    echo "  Scope:     maps/ only (--maps-only)"
else
    echo "  Scope:     full tree (maps, sprites, sound, models, ...)"
fi
echo

if [ "$MAPS_ONLY" = 1 ]; then
    [ -d "$SRC_DIR/maps" ] || { echo "ERROR: $SRC_DIR/maps missing" >&2; exit 1; }
    tar -C "$SRC_DIR" -czf "$OUT" maps
else
    tar -C "$SRC_DIR" -czf "$OUT" .
fi

FINAL_SIZE=$(du -sh "$OUT" | awk '{print $1}')
echo
echo "Bundle written: $OUT ($FINAL_SIZE)"
echo
echo "Top-level entries:"
tar -tzf "$OUT" | awk -F/ '{print $1}' | sort -u | head -10 || true   # info-only; tolerate SIGPIPE under pipefail
echo
echo "Transfer to the LAN box, then:"
echo "  mkdir -p /tmp/fastdl-staging"
echo "  tar -xzf $(basename "$OUT") -C /tmp/fastdl-staging"
echo "  # set FASTDL_FILES_PATH=\"/tmp/fastdl-staging\" in lan-deploy.conf"
