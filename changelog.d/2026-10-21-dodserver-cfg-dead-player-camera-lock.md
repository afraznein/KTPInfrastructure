### `config`: the online dodserver.cfg template carries the dead-player camera lock (2026-10-21)

`mp_forcechasecam 1` went live on all 24 through `/home/dod/distribute/dodserver.cfg` on
2026-10-12 and existed in no tracked template, so a config rebuilt from this repo would have
shipped without it. It is now in `config/online/dodserver.cfg.example`, in the same place and with
the same note as on the fleet. The engine re-execs that file on every `changelevel`
(`mapchangecfgfile`), which is the whole reason the line works: the two aim maps' per-map configs
set `mp_forcechasecam 0`, and before this guard the only things that put it back were a `.ready`
exec of `ktpbasic.cfg` and the nightly restart — so a match going live on a map with no `.ready`
config let dead players free-roam and see live positions.

`1` is the dll default and the value every instance already reads at map load, so the line is a
no-op against today's behaviour and becomes load-bearing the moment per-map configs start
executing again (`afraznein/KTPAMXX`#169). `test_online_example_keeps_the_dead_player_camera_lock`
pins the value and the `mapchangecfgfile` line it depends on. The lan and local profiles are left
alone: neither distributes to the fleet, and the lan warmup server runs stock HLDS.
