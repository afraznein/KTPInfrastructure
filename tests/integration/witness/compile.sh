#!/bin/bash
# KTPWitness Plugin Compiler — test-only plugin for Tier 2 integration tests.
#
# Mirrors KTPMatchHandler/compile.sh structure but:
#   - Outputs only to ./compiled/ here under tests/integration/witness/
#   - Does NOT auto-stage to KTP DoD Server (this plugin is never in production)
#   - No build_info.inc generation (the witness doesn't report a version via
#     amx_ktp_versions; it's transparent to the production reporter framework)

set -e

echo "========================================"
echo "KTPWitness Plugin Compiler (test-only)"
echo "========================================"
echo

KTPAMXX_DIR="/mnt/n/Nein_/KTP Git Projects/KTPAMXX"
KTPAMXX_BUILD="$KTPAMXX_DIR/obj-linux/packages/base/addons/ktpamx/scripting"
KTPAMXX_INCLUDES="$KTPAMXX_DIR/plugins/include"

if [ -n "${BASH_SOURCE[0]}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    SCRIPT_DIR="/mnt/n/Nein_/KTP Git Projects/KTPInfrastructure/tests/integration/witness"
fi
PLUGIN_NAME="KTPWitness"
OUTPUT_DIR="$SCRIPT_DIR/compiled"

TEMP_BUILD="/tmp/ktpwitnessbuild"

# ============================================
# Validation
# ============================================

if [ ! -f "$KTPAMXX_BUILD/amxxpc" ]; then
    echo "[ERROR] KTPAMXX Linux compiler not found!"
    echo "        Expected: $KTPAMXX_BUILD/amxxpc"
    echo "        Build it first: cd KTPAMXX && ./build_linux.sh"
    exit 1
fi

if [ ! -f "$KTPAMXX_INCLUDES/amxmodx.inc" ]; then
    echo "[ERROR] KTPAMXX includes not found!"
    echo "        Expected: $KTPAMXX_INCLUDES"
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/$PLUGIN_NAME.sma" ]; then
    echo "[ERROR] Source file not found: $PLUGIN_NAME.sma"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# ============================================
# Compile
# ============================================

echo "[INFO] Compiling $PLUGIN_NAME.sma..."
echo "       Compiler: $KTPAMXX_BUILD/amxxpc"
echo

# Wipe + recreate temp build dir to avoid nested-include accumulation per
# the same gotcha as KTPMatchHandler/compile.sh (cp -r src dst nests on re-run).
rm -rf "$TEMP_BUILD"
mkdir -p "$TEMP_BUILD"

cp "$KTPAMXX_BUILD/amxxpc" "$TEMP_BUILD/"
cp "$KTPAMXX_BUILD/amxxpc32.so" "$TEMP_BUILD/"
cp -r "$KTPAMXX_INCLUDES" "$TEMP_BUILD/include"

# Convert line endings on source
sed 's/\r$//' "$SCRIPT_DIR/$PLUGIN_NAME.sma" > "$TEMP_BUILD/$PLUGIN_NAME.sma"

cd "$TEMP_BUILD"
./amxxpc "$PLUGIN_NAME.sma" -i./include -i. -o"$PLUGIN_NAME.amxx"

if [ $? -ne 0 ]; then
    echo
    echo "========================================"
    echo "[FAILED] Compilation failed!"
    echo "========================================"
    exit 1
fi

cp "$PLUGIN_NAME.amxx" "$OUTPUT_DIR/"

echo
echo "========================================"
echo "[SUCCESS] Compilation successful!"
echo "========================================"
echo "Output: $OUTPUT_DIR/$PLUGIN_NAME.amxx"
echo
echo "[INFO] No staging — this is a test-only plugin. The integration test"
echo "       docker-compose mounts this binary into the test container's"
echo "       plugins/ directory directly."
echo
echo "Done!"
