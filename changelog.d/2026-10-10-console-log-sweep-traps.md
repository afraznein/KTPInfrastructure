### `docs`: three console-log sweep traps get a home beside the sweep methodology (2026-10-10)

`monitoring/fps_baselines/README.md` § Methodology now records why the scripts there glob
`*-console.log` and ignore filenames: only the first instance's live log is `dodserver-console.log`
(the rest carry LinuxGSM's `selfname`, so a glob on the 27015 name drops four instances per host and
reads as a clean zero), and a rotated log's filename is one day later than its contents, so dating a
record by its file shifts a whole day forward. It also records that flood-kick counts are not
comparable across 2026-10-05, when the fleet's `sv_rehlds_movecmdrate_max_avg` /
`sv_rehlds_stringcmdrate_max_avg` moved from 1800 / 250 to 10000 / 800 — a fall in kicks across that
date is the rule changing. All three had lived only on the TODO board.
