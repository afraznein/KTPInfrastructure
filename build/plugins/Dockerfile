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
        ./amxxpc "$source" -i./include -o"/output/plugins/$name.amxx" 2>&1 || echo "  WARNING: $name may have had errors"\n\
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
\n\
echo ""\n\
echo "========================================"\n\
echo "Compilation Complete"\n\
echo "========================================"\n\
ls -la /output/plugins/\n\
' > /build/compile_all.sh && chmod +x /build/compile_all.sh && /build/compile_all.sh

CMD ["ls", "-la", "/output/plugins/"]
