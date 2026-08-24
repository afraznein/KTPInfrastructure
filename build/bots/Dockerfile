# KTP local BOT game server — NOT PRODUCTION TOPOLOGY
#
# Derives from the ordinary local runtime image and adds the two things a bot
# needs that the KTP stack deliberately does not have: a Metamod loader, and a
# bot mod to load into it.
#
# ## Why this image exists separately
#
# DoD ships no bot AI. Stock `addbot` creates a fake-client slot that never
# joins a team and never spawns, so anything that needs a body in the world
# needs a third-party bot mod. The only Linux-viable DoD 1.3 bots are Marine
# Bot and new_bot, and both are **Metamod plugins** — while the KTP stack runs
# Metamod-free (ReHLDS extension mode: addons/extensions.ini loads ktpamx
# directly and liblist.gam keeps gamedll_linux at dlls/dod.so).
#
# So a bot cannot be added without changing the loader topology. That is a
# change to the stack under test, not a build detail, which is exactly why it
# is confined to its own image and its own compose service instead of being
# folded into runtime/Dockerfile.
#
# ## The topology: SPLIT LAYERS (this part is load-bearing)
#
#   engine  -> addons/extensions.ini -> ktpamx_i386.so   <- UNCHANGED, as prod
#   engine  -> liblist.gam           -> metamod_i386.so
#   metamod -> plugins.ini           -> new_bot_mm.so    <- bot ONLY
#   metamod -> +localinfo mm_gamedll -> dlls/dod.so
#
# Metamod hosts the BOT ONLY. ktpamx keeps loading through extensions.ini
# exactly as production does, so our plugins still run in extension mode.
#
# Letting Metamod host ktpamx as well **segfaults**: ktpamx logs "ReHLDS
# extension mode detected" even when Metamod loaded it, so it installs ReHLDS
# hookchains from inside Metamod's chain as well as at the engine layer.
# Three boot attempts upstream, three SIGSEGVs. See
# tests/e2e_stats/PHASE0_FINDINGS.md and tests/e2e_stats/metamod.py.
#
# ## This image is NOT enough on its own
#
# In extension mode KTPAMXX has no code path that registers a fake client as a
# player -- Connect()/PutInServer()/++g_players_num never run for a bot, so
# is_user_connected() is false and every AMXX-level plugin is blind to bots.
# A ktpamx built with KTP_LANE_B_FAKECLIENTS=1 is REQUIRED and is mounted at
# run time (see runtime/entrypoint-bots.sh, which refuses to boot without it).
#
# That failure is silent and looks exactly like a working server, which is why
# the entrypoint fails closed rather than warning.
#
# ## Redistribution
#
# This image contains third-party binaries that are not ours to redistribute.
# Local build artifact only -- never push it to a registry. The fleet consumes
# no images at all, so nothing here can reach production by accident.

ARG VERSION=latest
FROM ktp-gameserver:${VERSION}

ENV DEBIAN_FRONTEND=noninteractive

# 32-bit runtime for a 20-year-old bot .so. hlds itself is 32-bit so most of
# this is present already; listed explicitly because a missing libstdc++6:i386
# surfaces as an unhelpful "cannot open shared object".
#
# execstack is for diagnosis only: glibc >= 2.41 refuses shared libraries that
# want an executable stack, which is the single most likely reason an old bot
# .so fails to load on a current host.
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      libc6:i386 \
      libstdc++6:i386 \
      libgcc-s1:i386 \
      execstack \
      unzip \
      curl \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# new_bot — the DoD 1.3 bot AI.
#
# Source: https://dayofdefeat.home.blog/installer-2/ (0.2.2, changelog dated
# 13-07-2026 — actively maintained, not abandonware).
#
# Checksum-pinned on purpose: the upstream link is a Google Drive share with no
# version in the URL, no published checksum and no guarantee of stability.
# Pinning SHA-256 means a changed or replaced artifact FAILS THE BUILD instead
# of silently swapping the bot under a server whose whole job is trusting what
# it ran.
#
# Vendored override for when the Drive link rots or the host has no outbound
# internet:
#   docker build --build-arg NEW_BOT_URL=file:///vendor/new_bot-0.2.2.zip ...
#
# Kept byte-identical to build/lane-b/Dockerfile's block on purpose — same
# pins, same reasoning. If one moves, move both.
# ---------------------------------------------------------------------------
ARG NEW_BOT_VERSION=0.2.2
ARG NEW_BOT_URL=https://drive.google.com/uc?export=download&id=1KWxlqTNOe_yTXPZ3CLL13qTiz-cL-WYu
ARG NEW_BOT_SHA256=8f659fe14af21377c61e8c4645e2f0380d70cb33e4caf6f1f5caf4ed2d594f49

RUN set -eux; \
    curl -fsSL "$NEW_BOT_URL" -o /tmp/new_bot.zip; \
    echo "${NEW_BOT_SHA256}  /tmp/new_bot.zip" | sha256sum -c -; \
    unzip -q -o /tmp/new_bot.zip -d /opt/hlds; \
    rm -f /tmp/new_bot.zip; \
    rm -f /opt/hlds/dod/new_bot/new_bot_mm.dll; \
    test -f /opt/hlds/dod/new_bot/new_bot_mm.so; \
    chmod 0755 /opt/hlds/dod/new_bot/new_bot_mm.so; \
    echo "new_bot ${NEW_BOT_VERSION} installed"; \
    ls /opt/hlds/dod/new_bot/waypoints | wc -l

# ---------------------------------------------------------------------------
# Metamod-R — the plugin loader new_bot needs.
#
# Metamod-R rather than stock Metamod or metamod-p, because it is the ReHLDS
# fork and KTP runs KTP-ReHLDS. Its own README is blunt: "Metamod-r is
# incompatible with original HLDS. It is necessary to have installed ReHLDS
# (API 3.1+)".
# ---------------------------------------------------------------------------
ARG METAMOD_VERSION=1.3.0.149
ARG METAMOD_URL=https://github.com/rehlds/Metamod-R/releases/download/1.3.0.149/metamod-bin-1.3.0.149.zip
ARG METAMOD_SHA256=ede7f59c4e0220afe8c02aa348a130cce527f87d36ffdb674e37a501ce57be94

RUN set -eux; \
    curl -fsSL "$METAMOD_URL" -o /tmp/metamod.zip; \
    echo "${METAMOD_SHA256}  /tmp/metamod.zip" | sha256sum -c -; \
    unzip -q -o /tmp/metamod.zip 'addons/*' -d /opt/hlds/dod; \
    rm -f /tmp/metamod.zip /opt/hlds/dod/addons/metamod/metamod.dll; \
    test -f /opt/hlds/dod/addons/metamod/metamod_i386.so; \
    chmod 0755 /opt/hlds/dod/addons/metamod/metamod_i386.so; \
    cp /opt/hlds/dod/liblist.gam           /opt/hlds/dod/liblist.gam.production; \
    cp /opt/hlds/dod/addons/extensions.ini /opt/hlds/dod/addons/extensions.ini.production

# ---------------------------------------------------------------------------
# Wire the split-layer topology.
#
# Three edits, and the third one is the absence of an edit:
#   1. liblist.gam gamedll_linux -> metamod
#   2. metamod plugins.ini       -> new_bot ONLY (never ktpamx: see header)
#   3. extensions.ini            -> UNTOUCHED, still loads ktpamx
#
# Metamod still needs to be told which real game DLL to load underneath, and
# liblist.gam can no longer say (it now points at Metamod itself, so reading it
# would be circular). That is the `+localinfo mm_gamedll dlls/dod.so` on the
# compose command line.
# ---------------------------------------------------------------------------
RUN set -eux; \
    sed -i 's|^gamedll_linux .*$|gamedll_linux "addons/metamod/metamod_i386.so"|' \
        /opt/hlds/dod/liblist.gam; \
    grep -q 'metamod_i386.so' /opt/hlds/dod/liblist.gam; \
    printf '%s\n' \
      '; KTP local bot server -- TEST TOPOLOGY ONLY, never production.' \
      '; new_bot ONLY. ktpamx is deliberately absent: it loads via' \
      '; addons/extensions.ini as it does on the fleet, and letting Metamod' \
      '; host it too segfaults during plugin init (PHASE0_FINDINGS.md).' \
      'linux new_bot/new_bot_mm.so' \
      > /opt/hlds/dod/addons/metamod/plugins.ini; \
    grep -q 'ktpamx' /opt/hlds/dod/addons/extensions.ini

COPY runtime/entrypoint-bots.sh /entrypoint-bots.sh
RUN chmod +x /entrypoint-bots.sh

LABEL ktp.new_bot.version="${NEW_BOT_VERSION}"
LABEL ktp.metamod.version="${METAMOD_VERSION}"
LABEL ktp.topology="metamod-split — NOT production"
LABEL ktp.production="never — local test image, carries third-party binaries"

ENTRYPOINT ["bash", "/entrypoint-bots.sh"]
