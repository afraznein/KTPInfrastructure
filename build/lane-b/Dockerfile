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
#   3. It pins glibc to Ubuntu 22.04's 2.35. That is BELOW the 2.41 threshold
#      where the loader refuses shared libraries needing an executable stack,
#      which is the single most likely reason a 20-year-old DoD bot .so fails
#      to load on a modern host. Controlling glibc is a real advantage here,
#      not incidental.
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
      # Database for the ephemeral instance. MariaDB rather than MySQL: it is
      # the Ubuntu default, initialises without a root password ceremony, and
      # hlstats.pl talks to it through DBD::mysql either way.
      mariadb-server \
      mariadb-client \
      # hlstats.pl's DB layer. `perl -c hlstats.pl` aborts at `use DBI`
      # without these, so their absence would surface as a daemon that dies
      # three steps into a run rather than as a clear message.
      perl \
      libdbi-perl \
      libdbd-mysql-perl \
      # Test driver
      python3 \
      python3-pip \
      # 32-bit runtime for a third-party bot .so. hlds itself is 32-bit so most
      # of this is present already; listed explicitly because a missing
      # libstdc++6:i386 shows up as an unhelpful "cannot open shared object".
      libc6:i386 \
      libstdc++6:i386 \
      libgcc-s1:i386 \
      # Only needed if a bot .so requires an executable stack. Ubuntu 22.04's
      # glibc 2.35 does not enforce the 2.41 restriction, so this is here for
      # diagnosis rather than routine use.
      execstack \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir pytest

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

CMD ["bash", "-lc", "python3 -m pytest tests/e2e_stats -q"]
