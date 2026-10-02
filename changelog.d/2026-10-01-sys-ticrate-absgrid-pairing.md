### `config`: `sys_ticrate` follows the launch flags, not a fixed number (2026-10-01)

`config/online/dodserver.cfg.example` still said `sys_ticrate 1000`, while the
fleet runs `1500` with `-pingboost 2 -absgrid`. With the KTP engine's 1 ms
`-absgrid` grid, 1000 lets the `Host_FilterTime` gate reject about a third of
grid frames (~690 fps), and 1500 passes them (~1000 fps). A cfg rebuilt from
the example would have cost the fleet that. The example now carries 1500, with
the LAN template's explanation, and `docs/LINUXGSM.md`'s cloning recipe gains
the `-absgrid` its provisioner already writes.

`test_sys_ticrate_is_1000`, which pinned the stale number, is replaced by
`test_sys_ticrate_matches_the_profiles_launch_flags`. It reads each profile's
launch declaration from the repo (`provision/install-linuxgsm.sh`,
`docs/LINUXGSM.md`, the warmup README, `runtime/entrypoint.sh`) and requires
1500 with `-absgrid` and 1000 without. A profile whose launch line cannot be
found fails and says so instead of guessing.
