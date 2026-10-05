### `config`: dodserver.cfg templates carry the cmdrate average limits the fleet runs (2026-10-05)

`sv_rehlds_movecmdrate_max_avg 10000` and `sv_rehlds_stringcmdrate_max_avg 800` went live on all 24
through `/home/dod/distribute/dodserver.cfg` on 2026-10-05. They are now in `config/online/dodserver.cfg.example`,
`config/local/dodserver.cfg` and `config/lan/dodserver.cfg.example`, each next to its `max_burst`
sibling as on the fleet. The stock-HLDS warmup config is left alone: it has no ReHLDS cvars.
The online example's note on the avg limiters says what is still true of them (they measure against
realtime, so a paused server can trip one) rather than that they were never set.
`test_cmdrate_avg_limits_match_the_fleet` pins both values in all three templates.
