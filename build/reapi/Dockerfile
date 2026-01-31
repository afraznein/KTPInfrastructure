# KTPReAPI Builder
# Builds KTP-ReAPI (engine bridge module for KTPAMXX)

FROM ktp-base:latest

# Copy source directories
COPY KTPReAPI /build/KTPReAPI

WORKDIR /build/KTPReAPI

# Fix line endings on shell scripts
RUN sed -i 's/\r$//' build.sh && \
    sed -i 's/\r$//' reapi/version/appversion.sh && \
    chmod +x build.sh && \
    chmod +x reapi/version/appversion.sh

# Build using CMake
RUN bash build.sh -j=$(nproc)

# Create output directory with artifacts
RUN mkdir -p /output/ktpamx/modules && \
    cp build/reapi/reapi_ktp_i386.so /output/ktpamx/modules/ && \
    chmod +x /output/ktpamx/modules/*

CMD ["ls", "-la", "/output/ktpamx/modules/"]
