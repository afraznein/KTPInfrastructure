#!/bin/bash
# package-hlstatsx-bundle.sh — produce a portable HLStatsX install bundle.
#
# Run this on the production data server (74.91.112.242) to capture the
# /opt/hlstatsx/{scripts,sql}/ tree minus log output and the
# password-bearing hlstats.conf. Resulting tarball is suitable for
# HLSTATSX_SOURCE_PATH in a LAN deployment.
#
# Usage:
#   sudo ./package-hlstatsx-bundle.sh [output-tarball]
# Default output: /tmp/hlstatsx-bundle-<YYYYMMDD>.tar.gz
#
# Restore on the LAN box:
#   mkdir -p /tmp/hlstatsx-staging
#   tar -xzf hlstatsx-bundle-*.tar.gz -C /tmp/hlstatsx-staging
#   # then in lan-deploy.conf: HLSTATSX_SOURCE_PATH="/tmp/hlstatsx-staging"

set -eu -o pipefail

SRC_DIR=/opt/hlstatsx
DEFAULT_OUT=/tmp/hlstatsx-bundle-$(date +%Y%m%d).tar.gz
OUT=${1:-$DEFAULT_OUT}

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: run as root (need read access to $SRC_DIR/)" >&2
    exit 1
fi

if [ ! -d "$SRC_DIR" ]; then
    echo "ERROR: $SRC_DIR does not exist — is this the data server?" >&2
    exit 1
fi

if [ ! -f "$SRC_DIR/scripts/hlstats.pl" ]; then
    echo "ERROR: $SRC_DIR/scripts/hlstats.pl missing — bundle source looks broken" >&2
    exit 1
fi

if [ ! -f "$SRC_DIR/sql/install.sql" ]; then
    echo "ERROR: $SRC_DIR/sql/install.sql missing — bundle requires the upstream base schema" >&2
    exit 1
fi

echo "Packaging HLStatsX bundle from $SRC_DIR ..."
echo "  Output:   $OUT"
echo "  Excludes: hlstats.conf (contains DB password), logs/, *.log, .git*"
echo

# Pack from inside scripts/ + sql/ so paths in the archive are
# `scripts/...` and `sql/...` — matches the layout HLSTATSX_SOURCE_PATH
# expects (extracted dir contains scripts/ and sql/ subdirs).
tar -C "$SRC_DIR" \
    --exclude='scripts/hlstats.conf' \
    --exclude='scripts/logs' \
    --exclude='*.log' \
    --exclude='.git*' \
    -czf "$OUT" \
    scripts sql

FINAL_SIZE=$(du -sh "$OUT" | awk '{print $1}')
echo
echo "Bundle written: $OUT ($FINAL_SIZE)"
echo
echo "Contents:"
tar -tzf "$OUT" | head -20 || true   # info-only; tolerate SIGPIPE under pipefail
echo "  ..."
echo "  (total $(tar -tzf "$OUT" | wc -l) entries)"
echo
echo "Transfer to the LAN box (scp / rsync / USB), then:"
echo "  mkdir -p /tmp/hlstatsx-staging"
echo "  tar -xzf $(basename "$OUT") -C /tmp/hlstatsx-staging"
echo "  # set HLSTATSX_SOURCE_PATH=\"/tmp/hlstatsx-staging\" in lan-deploy.conf"
