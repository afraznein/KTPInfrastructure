### `docs`: ALERT_COVERAGE's own-weapon row no longer says the script is absent or that the health install pages hourly (2026-11-10)

The `ktp-own-weapon-kills.timer` row carried a 2026-11-07 reading that is wrong on
two counts. The report script was never absent: it is installed as
`/usr/local/bin/own_weapon_kills.py`, and the row's probe looked for
`ktp-own-weapon-kills*`, which matches nothing. And installing the health script
before the timer is enabled costs one state-change alert, not an hourly page,
because the health check reports a set-diff against its previous run.

The row now names the real script path and the order (timer first, then the health
script), and says how to settle both on the box.
