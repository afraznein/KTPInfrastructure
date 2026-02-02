# KTPAmxxCurl Builder
# Builds the non-blocking HTTP module for KTPAMXX with static linking
#
# This requires building 32-bit static libraries for:
# - zlib, openssl, c-ares, curl

FROM ktp-base:latest

# Install additional build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libssl-dev:i386 \
    && rm -rf /var/lib/apt/lists/*

# Create static lib output directory
RUN mkdir -p /usr/local/lib32/lib /usr/local/lib32/include

# Build 32-bit zlib
RUN cd /tmp && \
    wget -q https://zlib.net/zlib-1.3.1.tar.gz && \
    tar xzf zlib-1.3.1.tar.gz && \
    cd zlib-1.3.1 && \
    CFLAGS="-m32 -O3 -fPIC" ./configure --prefix=/usr/local/lib32 --static && \
    make -j$(nproc) && \
    make install && \
    cd / && rm -rf /tmp/zlib*

# Build 32-bit OpenSSL
RUN cd /tmp && \
    wget -q https://www.openssl.org/source/openssl-1.1.1w.tar.gz && \
    tar xzf openssl-1.1.1w.tar.gz && \
    cd openssl-1.1.1w && \
    ./Configure linux-generic32 no-shared no-async \
        --prefix=/usr/local/lib32 \
        --openssldir=/usr/local/lib32/ssl \
        -m32 -O3 -fPIC && \
    make -j$(nproc) && \
    make install_sw && \
    cd / && rm -rf /tmp/openssl*

# Build 32-bit c-ares (use GitHub releases)
RUN cd /tmp && \
    wget -q https://github.com/c-ares/c-ares/releases/download/cares-1_19_1/c-ares-1.19.1.tar.gz && \
    tar xzf c-ares-1.19.1.tar.gz && \
    cd c-ares-1.19.1 && \
    CFLAGS="-m32 -O3 -fPIC" LDFLAGS="-m32" \
    ./configure --prefix=/usr/local/lib32 --disable-shared --enable-static \
        --disable-tests --host=i686-pc-linux-gnu && \
    make -j$(nproc) && \
    make install && \
    cd / && rm -rf /tmp/c-ares*

# Build 32-bit curl with static linking
RUN cd /tmp && \
    wget -q https://curl.se/download/curl-8.5.0.tar.gz && \
    tar xzf curl-8.5.0.tar.gz && \
    cd curl-8.5.0 && \
    CFLAGS="-m32 -O3 -fPIC" LDFLAGS="-m32" \
    PKG_CONFIG_PATH=/usr/local/lib32/lib/pkgconfig \
    ./configure --prefix=/usr/local/lib32 \
        --disable-shared --enable-static \
        --with-openssl=/usr/local/lib32 \
        --with-zlib=/usr/local/lib32 \
        --enable-ares=/usr/local/lib32 \
        --disable-ldap --disable-ldaps \
        --disable-rtsp --disable-dict \
        --disable-telnet --disable-tftp \
        --disable-pop3 --disable-imap \
        --disable-smb --disable-smtp \
        --disable-gopher --disable-mqtt \
        --disable-manual --disable-libcurl-option \
        --without-libidn2 --without-libpsl \
        --without-brotli --without-zstd \
        --host=i686-pc-linux-gnu && \
    make -j$(nproc) && \
    make install && \
    cd / && rm -rf /tmp/curl*

# Copy source
COPY KTPAmxxCurl /build/KTPAmxxCurl

WORKDIR /build/KTPAmxxCurl

# Fix line endings
RUN find . -name "*.sh" -exec sed -i 's/\r$//' {} \;

# Build using manual compilation (like docker-build.sh)
RUN mkdir -p bin/ReleaseDLL obj && \
    STATIC_LIB_DIR="/usr/local/lib32" && \
    CXXFLAGS="-m32 -O3 -fPIC -std=c++14 -fno-stack-protector -DCURL_STATICLIB" && \
    DEFINES="-DNO_MSVC8_AUTO_COMPAT -DNDEBUG -DHAVE_STDINT_H -DASIO_STANDALONE" && \
    INCLUDES="-Ideps/halflife/dlls -Ideps/halflife/engine -Ideps/halflife/common -Ideps/halflife/public -Ideps/metamod -Ideps/asio -I${STATIC_LIB_DIR}/include" && \
    echo "Compiling source files..." && \
    g++ ${CXXFLAGS} ${DEFINES} ${INCLUDES} -c src/amx_curl_callback_class.cc -o obj/amx_curl_callback_class.o && \
    g++ ${CXXFLAGS} ${DEFINES} ${INCLUDES} -c src/asio_poller.cc -o obj/asio_poller.o && \
    g++ ${CXXFLAGS} ${DEFINES} ${INCLUDES} -c src/callbacks.cc -o obj/callbacks.o && \
    g++ ${CXXFLAGS} ${DEFINES} ${INCLUDES} -c src/curl_multi_class.cc -o obj/curl_multi_class.o && \
    g++ ${CXXFLAGS} ${DEFINES} ${INCLUDES} -c src/curl_natives.cc -o obj/curl_natives.o && \
    g++ ${CXXFLAGS} ${DEFINES} ${INCLUDES} -c src/curl_utils_class.cc -o obj/curl_utils_class.o && \
    g++ ${CXXFLAGS} ${DEFINES} ${INCLUDES} -c src/sdk/amxxmodule.cpp -o obj/amxxmodule.o && \
    echo "Linking with static libraries..." && \
    g++ -m32 -shared -Wl,-soname=amxxcurl_ktp_i386.so -s -o bin/ReleaseDLL/amxxcurl_ktp_i386.so \
        obj/amx_curl_callback_class.o \
        obj/asio_poller.o \
        obj/callbacks.o \
        obj/curl_multi_class.o \
        obj/curl_natives.o \
        obj/curl_utils_class.o \
        obj/amxxmodule.o \
        -Wl,--start-group \
        ${STATIC_LIB_DIR}/lib/libcurl.a \
        ${STATIC_LIB_DIR}/lib/libssl.a \
        ${STATIC_LIB_DIR}/lib/libcrypto.a \
        ${STATIC_LIB_DIR}/lib/libz.a \
        ${STATIC_LIB_DIR}/lib/libcares.a \
        -Wl,--end-group \
        -lpthread -lrt -ldl -static-libgcc -static-libstdc++ && \
    echo "Build complete!"

# Create output directory with artifacts
RUN mkdir -p /output/ktpamx/modules && \
    cp bin/ReleaseDLL/amxxcurl_ktp_i386.so /output/ktpamx/modules/ && \
    chmod +x /output/ktpamx/modules/*

CMD ["ls", "-la", "/output/ktpamx/modules/"]
