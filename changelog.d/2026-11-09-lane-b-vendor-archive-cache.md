### `lane-b`: the image build no longer fails a PR when a third-party host blinks (2026-11-09)

`build/lane-b/Dockerfile` fetched two archives at build time, each straight off a
third-party host with nothing between the build and an outage. On 2026-11-08 the
Metamod-R release asset answered `504` for the whole retry budget and the image
build died at `exit code: 22`, upstream of every harness test — so `corpus / Lane B`
went red on a PR that touched nothing related to it. It is not a required context,
so the PR reported `UNSTABLE` rather than blocked, but the lane measured nothing.

The retry budget was also spent the wrong way. `--retry 5 --retry-delay 5` ran out
of attempts while `--retry-max-time 120` still had most of its window left, so the
declared budget was never the binding constraint.

- CI now restores both archives from an `actions/cache` into `build/lane-b/vendor/`,
  and the Dockerfile prefers that copy over the network. The directory is committed
  (empty) because a `COPY` whose source matches nothing fails the build, so the
  builders that populate nothing still find it and fall through to `curl` exactly as
  before.
- The cache key is the two pinned sha256s, read out of the Dockerfile rather than
  copied into the workflow. Bumping a pinned version is therefore a miss by
  construction, and there are no `restore-keys` — a prefix match is how a bump would
  otherwise restore the archive it replaced.
- `sha256sum -c` stayed where it was, outside the branch, so the pin is checked
  whichever way the archive arrived. The workflow verifies independently before its
  save step, and deletes an archive that fails, so a bad entry cannot be stored and
  handed to every later run.
- `--retry` raised on both fetches so `--retry-max-time 120` is the thing that
  actually bounds them. `--retry-max-time` itself is unchanged.

The `--build-arg NEW_BOT_URL=file:///vendor/...` hint in that Dockerfile named a path
nothing ever mounted or copied in, so following it could not have worked. It now
names the vendor directory, which exists.

⚠️ **Verified by reading, `bash -n` and a stubbed simulation, not by a build** — there
is no Docker daemon on the workstation that prepared it. The first real exercise is
this change's own `corpus / Lane B` run, where a cache miss is expected and has to
succeed through the `curl` fallback.
