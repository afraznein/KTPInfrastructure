### `ops`: cron inventory re-captures the AC retention cron with its weapon hold (2026-11-12)

The `data` host's `cron.d/ktp-ac-retention` snapshot dated from 2026-08-25 and lacked the `WEAPON_RETENTION_DAYS=36500` line that has since been set live, so the inventory understated the hold (the script's own default is 365 days). Re-captured from the live file 2026-11-12 (0 secret findings, with a planted-value control).
