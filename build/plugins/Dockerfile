# KTP Plugins Builder
# Compiles all AMX plugins using the KTPAMXX compiler
#
# This uses a multi-stage build to get the compiler from ktp-amxx

# Build arg for versioning (set via docker-compose)
ARG VERSION=latest

# First, reference the amxx image to get the compiler
FROM ktp-amxx:${VERSION} AS amxx-compiler

# Now build plugins
FROM ktp-base:latest

# Copy compiler and includes from amxx build
COPY --from=amxx-compiler /output/ktpamx/scripting/amxxpc /compiler/amxxpc
COPY --from=amxx-compiler /output/ktpamx/scripting/amxxpc32.so /compiler/amxxpc32.so
COPY --from=amxx-compiler /output/ktpamx/scripting/include /compiler/include

# Copy all plugin source directories
COPY KTPMatchHandler /build/plugins/KTPMatchHandler
COPY KTPHLTVRecorder /build/plugins/KTPHLTVRecorder
COPY KTPCvarChecker /build/plugins/KTPCvarChecker
COPY KTPFileChecker /build/plugins/KTPFileChecker
COPY KTPAdminAudit /build/plugins/KTPAdminAudit
COPY KTPGrenades /build/plugins/KTPGrenades
COPY KTPPracticeMode /build/plugins/KTPPracticeMode
# KTPHudObserver source lives in JimmyLockhart65616/DoD-hud-observer
# (external repo, separate maintainer). Workflows check it out to the
# local path `KTPHudObserver/` so this COPY finds it.
COPY KTPHudObserver /build/plugins/KTPHudObserver

# AMXX stock plugins pulled from KTPAMXX source tree — prod load order
# lists admin.amxx (admin flag infrastructure) and stats_logging.amxx
# (DoD stats DODX hook) at the top of plugins.ini. Matches what's deployed
# on Denver 5 / ATL1 / NY1 (compiled against KTPAMXX includes, not stock
# AMXX 1.10 — hence built here instead of pulled from upstream tarball).
COPY --from=amxx-compiler /build/KTPAMXX/plugins/admin.sma          /build/plugins/amxx-stock/admin.sma
COPY --from=amxx-compiler /build/KTPAMXX/plugins/dod/stats_logging.sma /build/plugins/amxx-stock/stats_logging.sma
# stats_logging.sma #includes this by relative path, so it has to land in the
# same directory. Stock plugins are copied as individual files (not whole
# directories), so a new sibling include needs its own line here or the compile
# fails on a missing file.
COPY --from=amxx-compiler /build/KTPAMXX/plugins/dod/ktp_stats_capture.inc /build/plugins/amxx-stock/ktp_stats_capture.inc

WORKDIR /build

# Make compiler executable
RUN chmod +x /compiler/amxxpc

# Create output directory
RUN mkdir -p /output/plugins

# Create and run compile script
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
compile_plugin() {\n\
    local dir="$1"\n\
    local name="$2"\n\
    local source="$3"\n\
    \n\
    if [ -f "/build/plugins/$dir/$source" ]; then\n\
        echo "Compiling $name from $source..."\n\
        cd /compiler\n\
        # Convert line endings\n\
        sed "s/\\r$//" "/build/plugins/$dir/$source" > "$source"\n\
        ./amxxpc "$source" -i./include -i"/build/plugins/$dir" -o"/output/plugins/$name.amxx" 2>&1 || echo "  WARNING: $name may have had errors"\n\
        rm -f "$source"\n\
        if [ -f "/output/plugins/$name.amxx" ]; then\n\
            echo "  -> $name.amxx OK"\n\
        else\n\
            echo "  -> $name.amxx FAILED"\n\
        fi\n\
    else\n\
        echo "SKIP: /build/plugins/$dir/$source not found"\n\
    fi\n\
}\n\
\n\
echo "========================================"\n\
echo "KTP Plugin Compilation"\n\
echo "========================================"\n\
echo ""\n\
\n\
# Compile all plugins\n\
compile_plugin "KTPMatchHandler" "KTPMatchHandler" "KTPMatchHandler.sma"\n\
compile_plugin "KTPHLTVRecorder" "KTPHLTVRecorder" "KTPHLTVRecorder.sma"\n\
compile_plugin "KTPCvarChecker" "ktp_cvar" "ktp_cvar.sma"\n\
compile_plugin "KTPFileChecker" "ktp_file" "ktp_file.sma"\n\
compile_plugin "KTPAdminAudit" "KTPAdminAudit" "KTPAdminAudit.sma"\n\
compile_plugin "KTPGrenades" "KTPGrenadeLoadout" "KTPGrenadeLoadout.sma"\n\
compile_plugin "KTPGrenades" "KTPGrenadeDamage" "KTPGrenadeDamage.sma"\n\
compile_plugin "KTPPracticeMode" "KTPPracticeMode" "KTPPracticeMode.sma"\n\
compile_plugin "KTPHudObserver" "KTPHudObserver" "KTPHudObserver.sma"\n\
\n\
# AMXX stock plugins (compiled from KTPAMXX source — see above)\n\
compile_plugin "amxx-stock" "admin" "admin.sma"\n\
compile_plugin "amxx-stock" "stats_logging" "stats_logging.sma"\n\
\n\
echo ""\n\
echo "========================================"\n\
echo "Compilation Complete"\n\
echo "========================================"\n\
ls -la /output/plugins/\n\
' > /build/compile_all.sh && chmod +x /build/compile_all.sh && /build/compile_all.sh

CMD ["ls", "-la", "/output/plugins/"]
