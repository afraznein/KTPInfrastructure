# KTP Lane B — stats-capture end-to-end test runtime
#
# FROM the nightly runtime image, plus the three things Lane B needs that a
# game server does not: a database, the Perl DBI stack for hlstats.pl, and the
# 32-bit runtime a third-party bot .so wants.
#
# Why this image exists at all, when the earlier design used a copied
# serverfiles tree and a hand-rolled second mysqld on the Tier 2 runner:
#
#   1. amxxpc is ALREADY in the base image at
#      /opt/hlds/dod/addons/ktpamx/scripting/amxxpc, and smoke-callable.yml
#      already compiles plugins by docker-running it. The "no AMXX toolchain"
#      blocker was self-inflicted.
#   2. The container filesystem is ephemeral and isolated by construction, so
#      the fleet-matching serverfiles tree cannot be contaminated — no copy, no
#      hardlink write-through hazard, no integrity guard needed.
#   3. It pins glibc. The runtime base image is Ubuntu 24.04.4 (glibc 2.39) —
#      note that is NOT the same as build/base/Dockerfile's Ubuntu 22.04; the
#      runtime image is built separately, and 2.39 is what `ldd --version`
#      reports inside it. Still below the 2.41 threshold where the loader
#      refuses shared libraries needing an executable stack, which is the
#      single most likely reason a 20-year-old DoD bot .so fails to load on a
#      current host. Pinning it is a real advantage, but the margin is one
#      release — if the base image moves to a glibc >= 2.41 distro, expect the
#      bot to stop loading and reach for `execstack -c` below.
#   4. Lane B can then run on a GitHub-hosted runner and never touch the data
#      server — which also runs production HLStatsX and is deliberately
#      Docker-free.
#
# ## What this image is NOT
#
# It is a RECONSTRUCTION of the fleet, not the fleet. The production fleet is
# bare metal (5 hosts, artifacts staged as `.new` and swapped at the 03:00 ET
# restart — docs/DEPLOYING.md). This image is built from repo refs, so it
# mirrors the REPOS, not what is currently deployed. That is the right target
# for testing a branch, but "green in Lane B" is weaker evidence than "green on
# a fleet-matching tree", and nothing here should be read as retiring the
# Tier 2 runner's drift tripwire.
#
# ## The bot is NOT baked in
#
# Marine Bot / new_bot are third-party and not ours to redistribute, and baking
# one into an image that gets pushed to GHCR would publish it. It is mounted at
# runtime instead:
#
#   docker run -v "$PWD/bot-kit:/opt/bot-kit:ro" ...
#
# That also keeps the quarantine property intact — the image is publishable and
# carries no bot, and the fleet consumes no images at all.

ARG BASE_IMAGE=ghcr.io/afraznein/ktp-runtime-test-base:latest
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# i386 may already be enabled by the base build image; `dpkg --add-architecture`
# is idempotent, so re-asserting it costs nothing and makes this image
# independent of that assumption.
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      # Database for the ephemeral instance. MySQL, NOT MariaDB — this must
      # match production, which is MySQL 8.0.46 on the data server.
      #
      # This is not a preference. `sql/ktp_schema.sql` in KTPHLStatsX uses
      # `ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`, which is
      # MariaDB-only syntax that MySQL rejects at every version — the file's own
      # header documents this and warns that a FRESH install (LAN data-server
      # provisioning) is where it silently applies almost nothing. On MariaDB
      # those statements succeed, so a MariaDB-backed lane would go green on
      # exactly the migration hazard it exists to catch, and would keep doing so
      # right up until someone provisioned a real server.
      mysql-server \
      mysql-client \
      # hlstats.pl's DB layer. `perl -c hlstats.pl` aborts at `use DBI`
      # without these, so their absence would surface as a daemon that dies
      # three steps into a run rather than as a clear message.
      perl \
      libdbi-perl \
      libdbd-mysql-perl \
      # Test driver. pytest comes from apt rather than pip: Ubuntu 24.04 marks
      # the system Python as externally-managed (PEP 668), so `pip install`
      # fails outright, and --break-system-packages would be exactly the kind
      # of "make the error go away" fix that bites later. The harness itself is
      # stdlib-only; pytest is only needed to run the test files.
      python3 \
      python3-pytest \
      # The artifact build extracts every file with `git show <ref>:<path>`, so
      # git is a runtime dependency of the lane, not just a build-host one. The
      # runtime base image does not carry it.
      git \
      # 32-bit runtime for a third-party bot .so. hlds itself is 32-bit so most
      # of this is present already; listed explicitly because a missing
      # libstdc++6:i386 shows up as an unhelpful "cannot open shared object".
      libc6:i386 \
      libstdc++6:i386 \
      libgcc-s1:i386 \
      # Only needed if a bot .so requires an executable stack. The base image's
      # glibc 2.39 does not enforce the 2.41 restriction, so this is here for
      # diagnosis rather than routine use.
      execstack \
      # new_bot ships as a .zip
      unzip \
      ca-certificates \
      curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# new_bot — the DoD 1.3 bot AI, downloaded and installed at build time.
#
# Source: https://dayofdefeat.home.blog/installer-2/ (0.2.2, changelog dated
# 13-07-2026 — actively maintained, not abandonware).
#
# ## Checksum-pinned on purpose
#
# The upstream link is a Google Drive share, which has no version in the URL,
# no published checksum, and no guarantee of stability. Pinning SHA-256 means a
# changed or replaced artifact FAILS THE BUILD instead of silently swapping the
# bot under a test lane whose whole job is trusting what it ran. If upstream
# publishes 0.2.3, this build breaks loudly and someone updates both values
# deliberately — which is the correct amount of friction for a third-party
# binary in a test rig.
#
# Vendored override, for when the Drive link rots or the build host has no
# outbound internet:
#   docker build --build-arg NEW_BOT_URL=file:///vendor/new_bot-0.2.2.zip ...
#
# ## Redistribution
#
# This image now CONTAINS a third-party binary that is not ours to redistribute,
# so it must not be pushed to a public registry. It is a local/CI build
# artifact. The fleet consumes no images at all, so nothing here can reach
# production by accident.
# ---------------------------------------------------------------------------
ARG NEW_BOT_VERSION=0.2.2
ARG NEW_BOT_URL=https://drive.google.com/uc?export=download&id=1KWxlqTNOe_yTXPZ3CLL13qTiz-cL-WYu
ARG NEW_BOT_SHA256=8f659fe14af21377c61e8c4645e2f0380d70cb33e4caf6f1f5caf4ed2d594f49

RUN set -eux; \
    curl -fsSL "$NEW_BOT_URL" -o /tmp/new_bot.zip; \
    echo "${NEW_BOT_SHA256}  /tmp/new_bot.zip" | sha256sum -c -; \
    # The archive is rooted at `dod/`, and the game tree is /opt/hlds/dod, so
    # extracting at /opt/hlds lands every file exactly where it belongs.
    unzip -q -o /tmp/new_bot.zip -d /opt/hlds; \
    rm -f /tmp/new_bot.zip; \
    # Drop the Windows DLL: dead weight in a Linux image, and shipping a second
    # platform's binary invites someone to think this image is portable.
    rm -f /opt/hlds/dod/new_bot/new_bot_mm.dll; \
    test -f /opt/hlds/dod/new_bot/new_bot_mm.so; \
    # Ships 0644. dlopen does not require +x, but some HL plugin loaders check
    # it, and a missing exec bit is an annoying thing to debug through an
    # engine that just says "couldn't load".
    chmod 0755 /opt/hlds/dod/new_bot/new_bot_mm.so; \
    echo "new_bot ${NEW_BOT_VERSION}: $(ls /opt/hlds/dod/new_bot/waypoints | wc -l) waypoint files"

# Deliberately NOT activated here. new_bot is a Metamod plugin and the KTP
# stack runs Metamod-free (ReHLDS extension mode — addons/extensions.ini loads
# ktpamx directly, and liblist.gam still points gamedll_linux at dlls/dod.so).
# Installing the files is safe and inert; wiring it into a plugin loader is a
# change to the stack under test and belongs to the harness, at run time, where
# it is visible in a report rather than baked into a layer.
LABEL ktp.new_bot.version="${NEW_BOT_VERSION}"
LABEL ktp.new_bot.activated="false — needs Metamod, which the KTP stack does not use"

# Repos are bind-mounted from the host and owned by the host user, while the
# container runs as root, so git refuses them with "detected dubious ownership"
# and the artifact build fails before reading a single file.
#
# Waived rather than worked around, deliberately: the alternatives are worse.
# Running the container as the host uid breaks writes to /opt/hlds and the
# mysqld-as-root path; adding directories one at a time breaks the moment a
# repo moves. This is a throwaway test container with read-only repo mounts —
# the ownership check is protecting against a threat that does not exist here.
RUN git config --system --add safe.directory '*'

# MariaDB's packaging creates /var/lib/mysql and a system unit we never use —
# the harness runs mysqld directly on a private datadir under /tmp. Make sure
# the package's own instance can never start and confuse a run.
RUN rm -f /etc/init.d/mariadb /etc/init.d/mysql || true

# The harness lives here; mounted read-only at run time so an edit does not
# need an image rebuild during development.
WORKDIR /work

# Where the bot kit is expected. Empty in the image on purpose (see above).
RUN mkdir -p /opt/bot-kit

LABEL maintainer="KTP Infrastructure"
LABEL description="Lane B stats-capture e2e runtime: KTP stack + MariaDB + Perl DBI + 32-bit bot runtime"
LABEL ktp.lane="B"
LABEL ktp.production="never — test-only image, carries no bot, fleet consumes no images"

# Reset the inherited ENTRYPOINT. The runtime base image sets
# ENTRYPOINT ["/entrypoint.sh"], which boots hlds_linux — so anything passed to
# `docker run` lands as ARGUMENTS TO THE GAME SERVER instead of running.
#
# This is not hypothetical: the first real run of this image booted a DoD
# server and silently never executed the build script, and `docker top` showed
# the whole python command line appended to the hlds_linux argv.
# smoke-callable.yml sidesteps it per-invocation with `--entrypoint bash`;
# clearing it here means callers cannot forget.
#
# Lane B starts hlds itself, through the harness, when it wants a server —
# with the bot's `+localinfo mm_gamedll` argument and a test cfg the base
# entrypoint knows nothing about.
ENTRYPOINT []

CMD ["bash", "-lc", "python3 -m pytest tests/e2e_stats -q"]
