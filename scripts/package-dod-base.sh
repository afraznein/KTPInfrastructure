#!/bin/bash
# Package DoD Base Game Files
# Creates a tarball of base DoD content for deployment to servers
#
# Usage: ./package-dod-base.sh [source_path] [output_path]
#
# This packages all game content needed for a complete server:
#   - maps/*.bsp (all custom maps)
#   - *.wad (texture files)
#   - configs/*.cfg (KTP map configs like ktp_donner.cfg)
#   - models/, sprites/, sound/ (game assets)
#   - mapcycle.txt, motd.txt
#   - addons/ktpamx/configs/ (plugin configs)
#   - addons/ktpamx/data/ (gamedata, lang, GeoIP)
#
# Excludes binaries that come from our build (plugins, modules, dlls).

set -e

# Default paths (adjust for your environment)
# Source is the KTP test server which has proper configs, maps, etc.
DEFAULT_SOURCE="/mnt/n/Nein_/KTP Git Projects/KTP DoD Server/serverfiles/dod"
DEFAULT_OUTPUT="./dod-base-files.tar.gz"

SOURCE_PATH="${1:-$DEFAULT_SOURCE}"
OUTPUT_PATH="${2:-$DEFAULT_OUTPUT}"

echo "========================================"
echo "DoD Base Game Files Packager"
echo "========================================"
echo ""
echo "Source: $SOURCE_PATH"
echo "Output: $OUTPUT_PATH"
echo ""

# Verify source exists
if [ ! -d "$SOURCE_PATH" ]; then
    echo "ERROR: Source directory not found: $SOURCE_PATH"
    echo ""
    echo "Usage: $0 [source_path] [output_path]"
    echo ""
    echo "Example:"
    echo "  $0 '/mnt/g/SteamLibrary/steamapps/common/Half-Life/dod' './dod-base.tar.gz'"
    exit 1
fi

# Safety check: Warn if source has nested dod folder (incorrect source path)
if [ -d "$SOURCE_PATH/dod" ] && [ -d "$SOURCE_PATH/dod/maps" ]; then
    echo ""
    echo "WARNING: Source path appears to have a nested 'dod' folder!"
    echo "  Source: $SOURCE_PATH"
    echo "  Found: $SOURCE_PATH/dod/maps/"
    echo ""
    echo "This will create an incorrectly structured tarball with dod/dod/..."
    echo ""
    echo "The source path should be the 'dod' folder itself, e.g.:"
    echo "  Correct:   /path/to/serverfiles/dod"
    echo "  Incorrect: /path/to/serverfiles"
    echo ""
    echo "Aborting to prevent deployment issues."
    exit 1
fi

# Verify source has expected structure (maps folder exists)
if [ ! -d "$SOURCE_PATH/maps" ]; then
    echo ""
    echo "WARNING: Source path doesn't contain 'maps' folder."
    echo "  Expected: $SOURCE_PATH/maps/"
    echo ""
    echo "Make sure the source path points to the 'dod' folder itself."
    echo "Continue? (y/N)"
    read -r confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Aborted."
        exit 1
    fi
fi

# Create temp directory for filtered content
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

echo "Creating filtered copy..."

# Use rsync to copy with exclusions
# We EXCLUDE binaries that come from our build (plugins, modules, dlls)
# We INCLUDE configs, data, scripting includes, maps, models, etc.
rsync -a --progress \
    --exclude='addons/ktpamx/plugins/*.amxx' \
    --exclude='addons/ktpamx/modules/*.so' \
    --exclude='addons/ktpamx/dlls/*.so' \
    --exclude='addons/metamod/' \
    --exclude='rehlds/' \
    --exclude='addons/ktpamx/logs/' \
    --exclude='addons/ktpamx/configs/hltv_recorder.ini' \
    --exclude='addons/ktpamx/configs/discord.ini' \
    --exclude='configs/servernamedefault.cfg' \
    --exclude='*.log' \
    --exclude='*.dem' \
    --exclude='banned.cfg' \
    --exclude='listip.cfg' \
    --exclude='lservercache.dat' \
    "$SOURCE_PATH/" "$TEMP_DIR/dod/"

echo ""
echo "Contents summary:"
echo "  Maps: $(find $TEMP_DIR/dod/maps -name '*.bsp' 2>/dev/null | wc -l) files"
echo "  WADs: $(find $TEMP_DIR/dod -maxdepth 1 -name '*.wad' 2>/dev/null | wc -l) files"
echo "  Configs (dod/configs): $(find $TEMP_DIR/dod/configs -name '*.cfg' 2>/dev/null | wc -l) files"
echo "  Models: $(find $TEMP_DIR/dod/models -type f 2>/dev/null | wc -l) files"
echo "  Sounds: $(find $TEMP_DIR/dod/sound -type f 2>/dev/null | wc -l) files"
echo "  Sprites: $(find $TEMP_DIR/dod/sprites -type f 2>/dev/null | wc -l) files"
echo "  KTPAMX configs: $(find $TEMP_DIR/dod/addons/ktpamx/configs -type f 2>/dev/null | wc -l) files"
echo "  KTPAMX data: $(find $TEMP_DIR/dod/addons/ktpamx/data -type f 2>/dev/null | wc -l) files"
echo ""

echo "Creating tarball..."
tar -czf "$OUTPUT_PATH" -C "$TEMP_DIR" dod

echo ""
echo "========================================"
echo "Package created: $OUTPUT_PATH"
echo "Size: $(ls -lh "$OUTPUT_PATH" | awk '{print $5}')"
echo "========================================"
echo ""
echo "To deploy to a server:"
echo "  scp $OUTPUT_PATH dodserver@server:~/"
echo "  ssh dodserver@server 'tar -xzf dod-base-files.tar.gz -C ~/dod-27015/serverfiles/'"
