# KTPReHLDS Builder
# Builds the KTP-ReHLDS game engine (custom ReHLDS fork)

FROM ktp-base:latest

# Copy KTPReHLDS source
COPY KTPReHLDS /build/KTPReHLDS

WORKDIR /build/KTPReHLDS

# Fix line endings on shell scripts
RUN sed -i 's/\r$//' build.sh && \
    sed -i 's/\r$//' rehlds/version/appversion.sh && \
    chmod +x build.sh && \
    chmod +x rehlds/version/appversion.sh

# Build using CMake (build.sh creates ./build and runs cmake from there)
RUN bash build.sh -j=$(nproc)

# Create output directory with artifacts
# libsteam_api.so ships with KTPReHLDS (rehlds/lib/linux32/) — it must
# be deployed alongside hlds_linux and engine_i486.so.
RUN mkdir -p /output/engine && \
    cp /build/KTPReHLDS/build/rehlds/dedicated/hlds_linux /output/engine/ && \
    cp /build/KTPReHLDS/build/rehlds/engine_i486.so /output/engine/ && \
    cp /build/KTPReHLDS/rehlds/lib/linux32/libsteam_api.so /output/engine/ && \
    chmod +x /output/engine/*

# Default command just lists what was built
CMD ["ls", "-la", "/output/engine/"]
