#!/bin/bash
# package-hltv-bundle.sh — produce a portable HLTV-binaries tarball.
#
# Run this on the production data server (74.91.112.242) to capture the
# /home/hltvserver/hlds/ tree minus the recorded demos and the unused
# cstrike/ subtree. Resulting tarball is suitable for HLTV_BINARIES_PATH
# in a LAN deployment.
#
# Usage:
#   sudo ./package-hltv-bundle.sh [output-tarball]
# Default output: /tmp/hltv-bundle-<YYYYMMDD>.tar.gz
#
# Restore on the LAN box:
#   mkdir -p /tmp/hltv-staging
#   tar -xzf hltv-bundle-*.tar.gz -C /tmp/hltv-staging
#   # then in lan-deploy.conf: HLTV_BINARIES_PATH="/tmp/hltv-staging"

set -eu -o pipefail

HLTV_DIR=/home/hltvserver/hlds
DEFAULT_OUT=/tmp/hltv-bundle-$(date +%Y%m%d).tar.gz
OUT=${1:-$DEFAULT_OUT}

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: run as root (need read access to /home/hltvserver/hlds/)" >&2
    exit 1
fi

if [ ! -d "$HLTV_DIR" ]; then
    echo "ERROR: $HLTV_DIR does not exist — is this the data server?" >&2
    exit 1
fi

if [ ! -f "$HLTV_DIR/hlds_linux" ]; then
    echo "ERROR: $HLTV_DIR/hlds_linux missing — bundle source looks broken" >&2
    exit 1
fi

echo "Packaging HLTV bundle from $HLTV_DIR ..."
echo "  Output:   $OUT"
echo "  Excludes: *.dem (anywhere), demos/ dirs, cstrike/, configs/*.bak-*"
echo

# Exclude ALL demo files anywhere in the tree, not just dod/*.dem one level deep.
# The recorder drops recordings both in dod/demos/ (was 179G on prod) and loose
# in dod/ as auto_*/12man_* .dem (was ~25G), so a path-narrow exclude let tens of
# GB of demos into the "binaries" bundle. A global *.dem + demos-dir prune keeps
# the bundle to just binaries + game content (~4G).
HLTV_EXCLUDES=(
    --exclude='*.dem'
    --exclude='demos'
    --exclude='*/demos'
    --exclude='cstrike'
    --exclude='configs/*.bak-*'
    # Per-instance proxy configs are cluster-specific (prod ships 25 for
    # 27020-27044); the LAN provisioner regenerates the right set, so don't
    # ship them — they'd start stray proxies on the LAN box.
    --exclude='configs/hltv-*.cfg'
)

# Estimate size before tarring (rough — ignores compression).
RAW_SIZE=$(du -sh "${HLTV_EXCLUDES[@]}" "$HLTV_DIR" 2>/dev/null | awk '{print $1}')
echo "Estimated raw bundle size (pre-compression): $RAW_SIZE"
echo

# tar from inside the dir so paths in the archive are relative ("./hlds_linux"
# rather than "/home/hltvserver/hlds/hlds_linux") — makes the bundle
# trivially extractable into any HLTV_BINARIES_PATH target dir.
tar -C "$HLTV_DIR" \
    "${HLTV_EXCLUDES[@]}" \
    -czf "$OUT" \
    .

FINAL_SIZE=$(du -sh "$OUT" | awk '{print $1}')
echo
echo "Bundle written: $OUT ($FINAL_SIZE)"
echo
echo "Verify by listing top-level entries:"
tar -tzf "$OUT" | awk -F/ '{print $2}' | sort -u | head -15 || true   # info-only; tolerate SIGPIPE under pipefail
echo
echo "Transfer to the LAN box (scp / rsync / USB), then:"
echo "  mkdir -p /tmp/hltv-staging"
echo "  tar -xzf $(basename "$OUT") -C /tmp/hltv-staging"
echo "  # set HLTV_BINARIES_PATH=\"/tmp/hltv-staging\" in lan-deploy.conf"
