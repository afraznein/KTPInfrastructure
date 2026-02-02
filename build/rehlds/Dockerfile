# KTPReHLDS Builder
# Builds the KTP-ReHLDS game engine (custom ReHLDS fork)

FROM ktp-base:latest

# Copy KTPReHLDS source
COPY KTPReHLDS /build/KTPReHLDS

WORKDIR /build/KTPReHLDS/rehlds

# Fix line endings on shell scripts
RUN sed -i 's/\r$//' build.sh && \
    sed -i 's/\r$//' rehlds/version/appversion.sh && \
    chmod +x build.sh && \
    chmod +x rehlds/version/appversion.sh

# Build using CMake
RUN bash build.sh -j=$(nproc)

# Create output directory with artifacts
# Note: cmake subdirectory structure places outputs in different locations
RUN mkdir -p /output/engine && \
    cp /build/KTPReHLDS/rehlds/build/rehlds/dedicated/hlds_linux /output/engine/ && \
    cp /build/KTPReHLDS/rehlds/build/rehlds/engine_i486.so /output/engine/ && \
    chmod +x /output/engine/*

# Default command just lists what was built
CMD ["ls", "-la", "/output/engine/"]
