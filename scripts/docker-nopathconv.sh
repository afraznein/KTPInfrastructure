#!/usr/bin/env bash
# `docker`, with MSYS path rewriting turned off for this call only.
#
# Git Bash / MSYS rewrites POSIX-looking argv into Windows paths when invoking a
# Windows .exe, and it cannot tell a HOST path from a path INSIDE a container.
# So `docker run -w /build/KTPAMXX` arrives at the daemon as
#     -w 'C:/Program Files/Git/build/KTPAMXX'
# and is rejected as "not an absolute path".
#
# Turning the rewrite off for the whole shell is NOT a fix: `git -C /d/Git/...`
# then fails too, because git is also a native Windows binary and needs the
# conversion. And MSYS2_ARG_CONV_EXCL is not a fix either — excluding /build
# changes how the `host:container` form of -v is parsed, and the mount comes out
# as `C:\Users\lockh;C:`.
#
# So the scope has to be "docker invocations, and nothing else", which is
# exactly what this wrapper is. Pass it via the extension point the upstream
# script already provides:
#
#     LANEB_DOCKER=scripts/docker-nopathconv.sh scripts/build_ktpamx_laneb.sh
#
# Verified that Docker Desktop accepts unconverted POSIX host paths
# (`-v /c/Users/...:/x`), so both halves of a -v argument survive.
#
# No-op on Linux/macOS: MSYS_NO_PATHCONV means nothing there.
MSYS_NO_PATHCONV=1 exec docker "$@"
