# KTP Base Build Image
# Ubuntu 22.04 with GCC 32-bit development environment
# Used as base for all KTP component builds

FROM ubuntu:22.04

# Prevent interactive prompts during install
ENV DEBIAN_FRONTEND=noninteractive

# Set locale
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Add 32-bit architecture support and install build dependencies
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    # Core build tools
    build-essential \
    g++-multilib \
    gcc-multilib \
    cmake \
    make \
    nasm \
    # Python for AMBuild
    python3 \
    python3-pip \
    python3-venv \
    # Version control
    git \
    # Archive tools
    wget \
    curl \
    unzip \
    # 32-bit libraries
    lib32z1-dev \
    libc6-dev-i386 \
    linux-libc-dev:i386 \
    # Autotools (for some dependencies)
    autoconf \
    automake \
    libtool \
    pkg-config \
    # Clean up
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /build

# Verify 32-bit compilation works
RUN echo 'int main() { return 0; }' > /tmp/test.c && \
    gcc -m32 /tmp/test.c -o /tmp/test32 && \
    rm /tmp/test.c /tmp/test32

# Label
LABEL maintainer="KTP Infrastructure"
LABEL description="Base build environment for KTP game server components"
