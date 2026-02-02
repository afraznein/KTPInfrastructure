# KTPAMXX Builder
# Builds KTPAMXX (AMX Mod X fork) - scripting platform and plugin compiler

FROM ktp-base:latest

# Copy KTPAMXX source and dependencies
COPY KTPAMXX /build/KTPAMXX
COPY KTPhlsdk /build/KTPhlsdk
COPY metamod-am /build/metamod-am

WORKDIR /build/KTPAMXX

# Set up Python virtual environment and install AMBuild
RUN python3 -m venv /opt/ambuild-venv && \
    . /opt/ambuild-venv/bin/activate && \
    pip install --upgrade pip && \
    cd support/ambuild && \
    pip install . && \
    cd ../..

# Set environment variables for build
# Note: METAMOD headers needed for compilation even in extension mode
ENV HLSDK=/build/KTPhlsdk
ENV METAMOD=/build/metamod-am

# Fix any line ending issues
RUN find . -name "*.sh" -exec sed -i 's/\r$//' {} \;

# Configure and build
# --no-plugins: Skip plugin compilation (done separately)
# --no-mysql: Not needed for KTP
RUN . /opt/ambuild-venv/bin/activate && \
    python3 configure.py --enable-optimize --no-mysql --no-plugins && \
    cd obj-linux && \
    python3 $(which ambuild)

# Create output directory with artifacts
RUN mkdir -p /output/ktpamx/dlls /output/ktpamx/modules /output/ktpamx/scripting/include && \
    # Main binary (required)
    cp obj-linux/packages/base/addons/ktpamx/dlls/ktpamx_i386.so /output/ktpamx/dlls/ && \
    # DODX module (required for KTP)
    cp obj-linux/packages/dod/addons/ktpamx/modules/dodx_ktp_i386.so /output/ktpamx/modules/ && \
    # Optional modules (copy if they exist)
    cp obj-linux/packages/base/addons/ktpamx/modules/fun_ktp_i386.so /output/ktpamx/modules/ 2>/dev/null || true && \
    cp obj-linux/packages/base/addons/ktpamx/modules/engine_ktp_i386.so /output/ktpamx/modules/ 2>/dev/null || true && \
    cp obj-linux/packages/base/addons/ktpamx/modules/fakemeta_ktp_i386.so /output/ktpamx/modules/ 2>/dev/null || true && \
    # Compiler (required)
    cp obj-linux/packages/base/addons/ktpamx/scripting/amxxpc /output/ktpamx/scripting/ && \
    cp obj-linux/packages/base/addons/ktpamx/scripting/amxxpc32.so /output/ktpamx/scripting/ && \
    # Include files
    cp -r plugins/include/* /output/ktpamx/scripting/include/ && \
    # Set permissions
    chmod +x /output/ktpamx/dlls/* /output/ktpamx/modules/* /output/ktpamx/scripting/amxxpc && \
    # List what was built
    echo "Built artifacts:" && ls -la /output/ktpamx/dlls/ /output/ktpamx/modules/

CMD ["ls", "-laR", "/output/ktpamx/"]
