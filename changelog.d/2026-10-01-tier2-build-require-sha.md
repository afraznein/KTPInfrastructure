### `tier2`: the KTPMatchHandler build refuses any tree but the pinned commit (2026-10-01)

`tier2-integration.yml` compiled its reviewed KTPMatchHandler from a checkout
pinned by `ref:`, but the build never confirmed the tree it compiled was that
commit, and it baked `git rev-parse --short HEAD` inside a `printf` argument,
where a failure left an empty SHA and the step went on. The pin now lives once,
as job env `KTP_MATCHHANDLER_SHA`, read by the checkout. Before compiling, the
build runs the new `scripts/tier2-require-sha.sh`, which fails the run unless
the checkout resolves to exactly that 40-hex commit with a clean tree. The SHA
it prints is the one baked into the artifact.
