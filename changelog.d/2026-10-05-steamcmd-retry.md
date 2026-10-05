### `runtime`: the HLDS install layer retries a transient steamcmd failure (2026-10-05)

`publish-base-image` failed on 2026-09-30 and 2026-10-05 with steamcmd exiting 8 after
`Error! App '90' state is 0x10E` / `0x202 after update job` — Steam-side update-job states that a
rerun clears. The `app_update 90` layer in `runtime/Dockerfile` now runs up to three attempts, 30 s
apart, and still fails the build with steamcmd's own exit code once they are spent. The steamcmd
arguments are unchanged. `tests/unit/test_runtime_dockerfile_steamcmd_retry.py` runs the layer under
`/bin/sh` against a fake steamcmd.
