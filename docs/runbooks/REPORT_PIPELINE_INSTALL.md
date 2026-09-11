# Report pipeline: first install on the data server

Match reports are built on `neindataatl` and pushed to the website. Nothing in
this pipeline existed on the box before Season 10; this runbook is the install.

Three commands run in order on a timer: `generate` turns finished matches in
`hlstatsx` into report rows, `aggregate` rolls those into season totals, and
`report_sync` pushes both to Supabase for ktpleague.gg to read.

Everything below needs root. It is a one-time setup.

## 1. Service account

Not `krodssh`. That is an interactive login for analysis and has never run
automation. The pipeline gets its own identity with the same reads, plus write
on exactly the two tables it owns.

Confirm the auth plugin first, because the `CREATE USER` below depends on it:

```bash
sudo mysql -N -e "SELECT user, host, plugin FROM mysql.user WHERE user='krodssh';"
```

Expect `auth_socket`. Anything else and the `CREATE USER` needs a different
clause — stop and ask rather than improvising one.

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin ktpreports
sudo mysql -e "CREATE USER 'ktpreports'@'localhost' IDENTIFIED WITH auth_socket AS 'ktpreports';"
```

The Linux user and the MySQL user must have the same name. `auth_socket`
authenticates by peer credential, so a mismatch fails at connect time with a
confusing access-denied rather than anything that names the cause.

Mirror the reads rather than hand-copying 227 grants:

```bash
sudo mysql -N -B -e "SHOW GRANTS FOR 'krodssh'@'localhost'" \
  | sed "s/krodssh/ktpreports/g" > /tmp/mirror_grants.sql
# read it before applying it
sudo mysql < /tmp/mirror_grants.sql
```

Then the two tables it writes:

```bash
sudo mysql -e "GRANT INSERT, UPDATE ON hlstatsx.ktp_match_reports TO 'ktpreports'@'localhost';
GRANT INSERT, UPDATE ON hlstatsx.ktp_web_season_aggregates TO 'ktpreports'@'localhost';"
```

## 2. Deployment checkout

A real checkout owned by `ktpreports`. Not the Actions runner's work directory
under `/opt/ktp-tier2-runner`, which is CI scratch and gets wiped. Not
`/opt/ktp-infra` either — that is a separate, deliberately stale copy that the
weekly fleet audit runs from and that never pulls.

```bash
sudo install -d -o ktpreports -g ktpreports /opt/ktp-reports
sudo -u ktpreports git clone https://github.com/afraznein/KTPInfrastructure.git \
  /opt/ktp-reports/KTPInfrastructure
```

## 3. The Supabase secret

```bash
sudo install -d -m 0750 -o root -g ktpreports /etc/ktp
sudo install -m 0640 -o root -g ktpreports /dev/null /etc/ktp/reports.env
```

Then write into `/etc/ktp/reports.env`:

```
KTP_SUPABASE_URL=https://yxpjfenpnwksvvquqlde.supabase.co
KTP_SUPABASE_SECRET_KEY=<service-role secret>
```

This is the **service-role** secret, not the publishable key. The publishable
key is read-only and public by design; this job writes. It must never reach a
game server or the website repo.

## 4. Install the units

```bash
sudo install -m 0644 /opt/ktp-reports/KTPInfrastructure/systemd/ktp-reports.service /etc/systemd/system/
sudo install -m 0644 /opt/ktp-reports/KTPInfrastructure/systemd/ktp-reports.timer   /etc/systemd/system/
sudo systemctl daemon-reload
```

Dry-run the sync before arming anything. This is the step that catches a
misplaced or unreadable secret, and it writes nothing:

```bash
sudo -u ktpreports env -u USER -u LOGNAME $(sudo cat /etc/ktp/reports.env | xargs) \
  python3 -m scripts.report_sync --dry-run
```

Run it from `/opt/ktp-reports/KTPInfrastructure`. It should report what it
would push and exit 0. `missing env KTP_SUPABASE_URL` means the file is not
readable by the account — check group ownership and the `0640` mode.

`-u USER -u LOGNAME` is load-bearing rather than tidiness. `sudo -u` leaves
`$USER` set to the invoking user, and the `mysql` client takes its default
username from that — so without it the command authenticates as **root** and
`auth_socket` refuses with `ERROR 1698 (28000): Access denied for user
'root'@'localhost'`, which reads exactly like a broken pipeline. The systemd
unit is unaffected, because `User=ktpreports` sets the environment correctly.
This only bites when a human runs a step by hand.

Then arm it:

```bash
sudo systemctl enable --now ktp-reports.timer
systemctl list-timers ktp-reports.timer
```

## 5. Confirm after the first real match

Three counts, walking the chain in order. The first that reads zero says where
it stopped.

```sql
SELECT COUNT(*) FROM ktp_match_reports;          -- generate ran
SELECT COUNT(*) FROM ktp_web_season_aggregates;  -- aggregate ran
```

Then open <https://ktpleague.gg/stats/matches>. The empty-state text should be
gone and the match listed.

| Symptom | Cause |
|---|---|
| 0 reports | Timer never fired, or the match is before the `--since` floor |
| Reports but 0 aggregates | `aggregate` failed; read the second ExecStart in the journal |
| Both built, site empty | `report_sync` did not push. Almost always the secret |
| A rating renders negative | Checkout is behind `main`; the display floor is 50 |

```bash
journalctl -u ktp-reports.service -n 50 --no-pager
```

### Use the verifier, not a row count

`SELECT COUNT(*) FROM ktp_match_reports` returns 0 when the timer never ran,
when it ran and correctly found nothing, and when it ran and failed — and the
site answers 200 in all three. The verifier tells those apart and exits
non-zero when the pipeline is broken:

```bash
cd /opt/ktp-reports/KTPInfrastructure
sudo -u ktpreports env -u USER -u LOGNAME   python3 -m scripts.verify_report_pipeline --since 2026-09-13 --site https://ktpleague.gg
```

It reads `/var/log/ktp-report-service.log`, which the unit writes via
`StandardOutput=append:`. If that file is absent the `RAN` check fails, which
is the correct answer to "did it run" rather than a fault in the verifier.

## The `--since` floor

`ktp-reports.service` pins `--since 2026-09-13`. Everything before that date is
pre-season pracc and scrim traffic with no official standing, and there is no
official/scrim flag in the schema, so this date is the only thing separating
them. Widening it publishes practice matches as league results.

Nothing is lost by a late install. `generate` reads `hlstatsx` retroactively, so
matches played before the timer existed still publish on the first run.
