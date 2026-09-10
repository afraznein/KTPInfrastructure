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
# Plugins that did not produce a usable .amxx. Collected rather than exited on,\n\
# so one build reports EVERY broken plugin instead of stopping at the first.\n\
# Checked at the end; a non-empty list fails the build.\n\
#\n\
# It used to be neither. The compile was `|| echo "WARNING: ... may have had\n\
# errors"`, which also neutralised the `set -e` above, and the missing-artifact\n\
# branch printed FAILED and returned 0. So a plugin that failed to compile\n\
# produced a SUCCESSFUL build whose image simply lacked that .amxx -- and a\n\
# server that loads no stats_logging.amxx collects nothing at all, silently,\n\
# with every build and deploy step reporting success.\n\
FAILED_PLUGINS=""\n\
\n\
compile_plugin() {\n\
    local dir="$1"\n\
    local name="$2"\n\
    local source="$3"\n\
    local ok=1\n\
    \n\
    if [ -f "/build/plugins/$dir/$source" ]; then\n\
        echo "Compiling $name from $source..."\n\
        cd /compiler\n\
        # Convert line endings\n\
        sed "s/\\r$//" "/build/plugins/$dir/$source" > "$source"\n\
        if ! ./amxxpc "$source" -i./include -i"/build/plugins/$dir" -o"/output/plugins/$name.amxx" 2>&1; then\n\
            ok=0\n\
            echo "  -> $name: amxxpc reported errors"\n\
        fi\n\
        rm -f "$source"\n\
        # Checked separately from the exit status: a cached or stale artifact can\n\
        # outlive a failed compile, and an absent one is unambiguous either way.\n\
        if [ ! -f "/output/plugins/$name.amxx" ]; then\n\
            ok=0\n\
            echo "  -> $name: no .amxx produced"\n\
        fi\n\
        if [ "$ok" = "1" ]; then\n\
            echo "  -> $name.amxx OK"\n\
        else\n\
            FAILED_PLUGINS="$FAILED_PLUGINS $name"\n\
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
if [ -n "$FAILED_PLUGINS" ]; then\n\
    echo "PLUGIN BUILD FAILED:$FAILED_PLUGINS"\n\
    echo "========================================"\n\
    ls -la /output/plugins/\n\
    exit 1\n\
fi\n\
echo "Compilation Complete"\n\
echo "========================================"\n\
ls -la /output/plugins/\n\
' > /build/compile_all.sh && chmod +x /build/compile_all.sh && /build/compile_all.sh

CMD ["ls", "-la", "/output/plugins/"]
