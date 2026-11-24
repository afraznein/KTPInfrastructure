### `docs`: three `ALERT_COVERAGE.md` claims settled against the box (2026-11-07)

Read-only on the data server and all five game hosts; every count carries its haystack and a
nonsense-token control.

- **Hole 1's fleet half is closed and had been for weeks.** `ktp-fleet-health.sh` is md5
  `59b77b0d2f996d341bff90fd0cff581a` on all five game hosts, byte-identical to
  `monitoring/fleet-health/ktp-fleet-health.sh`, one crontab line each, and the state file's mtime
  was 2026-11-07 01:08–01:09 on all five at once. The entry said *"open on the fleet"* because
  closing the repo half and closing the fleet half are two acts and only the first leaves a commit.
- **`ktp-install-freshness.timer` is NOT an unclearable hourly page**, and the stale side was this
  repo. The timer is `loaded` / `enabled` / `active` on the box, last run 2026-11-06 06:24:52 EST —
  while `scripts/systemd/ktp-install-freshness.timer` still carried
  `⛔ NOT INSTALLED OR ENABLED — proposal` on its first line and its `.service` twin beside it said
  `✅ LIVE: installed and enabled`. The pair contradicted itself and the runbook row was built on
  the wrong half. 🔑 `scripts/ktp-install-freshness.sh` already records that this same header
  *"said NOT INSTALLED OR ENABLED for weeks after it was turned on"* — so it rotted twice, and the
  remedy written in is the `systemctl show` derivation rather than a third corrected sentence.
- **`ktp-own-weapon-kills.timer` is the entry that WILL page, and only once the health script is
  installed.** The units are on the box and `loaded`, with the on-failure drop-in, but
  `UnitFileState=disabled` / `ActiveState=inactive`; the report script is absent from
  `/usr/local/bin`; and the deployed `ktp-data-server-health.sh` (md5 `07b55aea…`, 96,146 B, Oct 28)
  does not carry the entry at all — 0 hits for `own-weapon-kills` against a positive control of 1
  for `map-coefficients`. So the live array is **14** against **15** here, and the gap is exactly
  this row. The 10-31 changelog's *install the units before or with the health script* is met and
  still not sufficient: the `CRITICAL_TIMERS` leg wants `active` **and** `enabled`, and
  installed-but-disabled fails it the same way absent does.

⚠️ **Deployed-vs-repo is the live gap, not a figure in a doc.** The health script on the box is
6,107 B behind `origin/main` and that is what makes the own-weapon-kills page latent rather than
firing. Nothing in this change touches the box.
