# Runbook: alert severity, lanes, and how to land the rest of it

Companion to [`ALERT_COVERAGE.md`](ALERT_COVERAGE.md), which answers *what is watched*.
This one answers *where it lands, and how loud*.

**Measured 2026-09-15** against all five game hosts and the data server, read-only.
Re-derive anything you act on; the figures here are a snapshot.

## The problem, in numbers

`#ktp-crashes` (`1497957091107668070`) is simultaneously the crash channel, the health
channel, the perf channel, the spike-digest channel and the ops-digest channel. Seven
producers write to it, one of them (`ktp-admin-bot`'s `ops_alerts` cog) through the Discord
gateway rather than the relay, so a routing change made at the relay does not reach it.

Positively accounted traffic, 2026-09-09 → 09-15:

| Producer | Posts in the week | Record it came from |
|---|---|---|
| `ktp-data-server-health.sh` | 22 | `alert posted (HTTP 200)` in its log |
| `ktp-spike-digest` | 7 | `relay OK` in `/var/log/ktp-spike-digest.log` |
| `ktp-perf-rollup` | 0 | last `relay OK (200)` is 2026-08-16 |
| `crashreporter` × 5 hosts | 0 | no `/tmp/core.*` in 30 days, positive control ran |
| `ops_alerts` cog | **unknown** | posts via gateway, writes no file, journal holds ~2 days |
| aggregator spike alerts | **unknown** | `SPIKE_ALERTS_ENABLED=1`, no log line on success |

The channel is not crash-dominated. It is dominated by an hourly health script firing on
every service state transition — and the crashreporter's zero, which is the *correct*
outcome, is indistinguishable in that channel from the crashreporter being broken.

Separately, the scheduled game-server restart posts **10 messages / 20 HTTP POSTs a day**
fleet-wide (below), none of which say anything on a normal night.

## Severity and lanes

Set by `scripts/ktp_alert_routing.py` and its shell twin `scripts/ktp-alert-routing.sh`.

| Severity | Glyph | Colour | Default lane | Means |
|---|---|---|---|---|
| `page` | 🔴 | `15548997` | `page` | wake someone; something is down or lost |
| `warn` | 🟠 | `16763904` | `ops-daily` | look today; a trend crossed a line |
| `info` | ⚪ | `9807270` | `ops-daily` | a record, not a request |
| `recovery` | 🟢 | `5763719` | `page` | the page above it is over |

Lanes are **roles, not ids**. A lane's id is read from `KTP_CHANNEL_PAGE`,
`KTP_CHANNEL_OPS_DAILY`, `KTP_CHANNEL_OPS_WEEKLY` or `KTP_CHANNEL_COMMUNITY` — environment
first, then `/etc/ktp/discord-relay.conf`, then the producer's existing channel. Nothing
guesses an id: a lane with no mapping and no legacy channel raises.

That fallback is what makes the code safe to merge ahead of the config. **Until the keys are
set, every producer posts exactly where it posts today.**

## Three rules

1. **Silence means healthy.** A green run posts nothing unless the run before it was not.
2. **A confirmation that scheduled work succeeded is not an alert.** It is a line appended to a
   local spool file, `/var/lib/ktp-alerts/<lane>.jsonl`, on the host that ran. That file is a
   record only: nothing reads it, and nothing delivers it to Discord.
3. **One glyph set, set by the helper.** No producer carries colour constants.

Four producers already worked this way and were the model: `ktp-perf-rollup`,
`ktp-tier2-heartbeat`, `ktp-soak-verify` and the bot's alert engine all post nothing when
green.

---

# Tier 1 — landed in the repo

See the changelog fragment for the full list. What an operator needs:

## Deploying it

⚠️ **`ktp-alert-routing.sh` must land before the producers that source it.** They abort with
`exit 3` and a message on stderr rather than posting the wrong colour or nothing at all.

```bash
# data server, as root — from a checkout of main, NOT from /opt/ktp-infra
install -m 0755 scripts/ktp-alert-routing.sh /usr/local/bin/ktp-alert-routing.sh
install -m 0755 scripts/ktp_alert_routing.py /usr/local/bin/ktp_alert_routing.py
install -d -m 0755 /var/lib/ktp-alerts
# then the producers
for f in hltv-restart-all.sh ktp-demo-retention.sh ktp-backup-watchdog.sh \
         ktp-hltv-liveness.sh ktp-scheduled-kernel-reboot.sh; do
  install -m 0755 "scripts/$f" "/usr/local/bin/$f"
done
install -m 0755 scripts/ktp-soak-verify.py /usr/local/bin/ktp-soak-verify
install -m 0755 scripts/precache_audit.py  /usr/local/bin/ktp-precache-audit
```

Verify without waiting for a timer — `hltv-restart-all.sh` restarts 24 proxies, so do **not**
run it to test. Test the decision instead:

```bash
. /usr/local/bin/ktp-alert-routing.sh
ktp_alert_route page   && echo "$KTP_ALERT_GLYPH $KTP_ALERT_COLOR $KTP_ALERT_LANE"  # 🔴 15548997 page
ktp_alert_channel ops-daily 1497957091107668070 && echo "$KTP_ALERT_CHANNEL ($KTP_ALERT_CHANNEL_SOURCE)"
python3 /usr/local/bin/ktp_alert_routing.py info --producer hltv-restart-all \
        --legacy-channel 1497957091107668070 --json
```

## What it looks like the first time it runs

- **`hltv-restart-all.sh`, 03:00 and 11:00** — on a clean run, *nothing appears in Discord*.
  The absence is the change. Partial, failed and first-green-after-failure ("recovery") runs
  still post to both HLTV status channels. The unit is `hltv-restart.service`, fired by
  `hltv-restart.timer` (a oneshot with no `StandardOutput` redirect, so there is **no**
  `/var/log/hltv-restart.log`; output goes to the journal). Confirm a run in three places:
  1. the state file changed: `stat -c '%y %n' /var/lib/ktp-alerts/hltv-restart-all.state`
     (it holds the last severity; the mtime moves every run);
  2. the journal: `journalctl -u hltv-restart.service --since "today 02:55"` shows
     `Clean restart (24/24 connected) — digest line, no post.`;
  3. the spool: `tail -n 2 /var/lib/ktp-alerts/ops-daily.jsonl` holds one line per clean run
     (`HLTV: 24/24 proxies restarted and connected`).
  ⚠️ **The spool is a local record, not a digest that gets posted.** Nothing reads it to
  Discord. The clean-run branch of `scripts/hltv-restart-all.sh` (byte-identical to the
  deployed `/usr/local/bin` copy) only appends, and posts nothing:
  ```bash
  else
      echo "$LOG_PREFIX Clean restart ($SUCCESS/$TOTAL connected) — digest line, no post."
      ktp_alert_spool_line hltv-restart-all info \
          "HLTV: $SUCCESS/$TOTAL proxies restarted and connected" ops-daily || true
  fi
  ```
  `ktp_alert_spool_line` in `ktp-alert-routing.sh` ends in one append, `>> "$dir/$lane.jsonl"`.
  The only reader in the repo is `drain_digest_lines()` in `ktp_alert_routing.py`, and nothing
  calls it. "Digest line" in the journal message names the format; nothing is delivered. The file
  grows until a consumer is built; that gap is tracked in [ALERT_COVERAGE.md](ALERT_COVERAGE.md).
- **First run only**, `/var/lib/ktp-alerts/hltv-restart-all.state` does not exist. A clean
  run is treated as routine and stays quiet — deliberately: an all-clear for a page nobody
  saw is worse than one more silent night.
- **Colours change on the next failure post.** A partial restart is 🟠 `#FFCC00` where it was
  pure orange; the same content.
- Every other producer's behaviour is unchanged. Only its embed colour moves.

## Rollback

`/usr/local/bin` copies only — nothing here touches the game fleet or `/home/dod/distribute/`.
Reinstall the previous script from the commit before the deploy. The helper can stay: an
unsourced helper does nothing.

---

# Tier 2 — host-side, `ktp-scheduled-restart.sh`

⛔ **Do not apply this. It is an operator act.** The script is gitignored by design, host-only,
and double-guarded: `scripts/deploy-restart-script.py` refuses a canonical that has drifted
from the tracked `.example` (#369), and `tests/unit/test_deploy_restart_example_guard.py`
asserts the `.example` equals the live canonical minus its two placeholders. **A comment
changed on one side and not the other registers as deploy drift.**

## What is there now (measured 2026-09-15)

`/home/dodserver/ktp-scheduled-restart.sh`, md5 `4c5297d20e01d7910a2056cfdd8ae49e` — **byte
identical on all five hosts**, 31779 bytes, 732 lines, mtime Sep 10 13:33. Invoked from the
`dodserver` crontab, not systemd:

```
0 3 * * * /home/dodserver/ktp-scheduled-restart.sh >> /home/dodserver/log/scheduled-restart.log 2>&1
```

Four Discord call sites, two visible messages:

| Line | Event | Channel | Colour | Fires on a clean night? |
|---|---|---|---|---|
| 250 | "Server Restart In Progress" | `CHANNEL_KTP` | `COLOR_ORANGE` | always |
| 251 | same message, same instant | `CHANNEL_EXTERNAL` | `COLOR_ORANGE` | always |
| 716 | final status, **edit** of #1 | `CHANNEL_KTP` | green/orange/red | **yes** |
| 719 | final status, **edit** of #2 | `CHANNEL_EXTERNAL` | green/orange/red | **yes** |

**Volume:** 2 messages + 4 HTTP POSTs per host per run × 5 hosts × 1 run/day =
**10 messages / 20 POSTs per day**, verified from `~/log/scheduled-restart.log` on all five
hosts for 2026-09-06 → 09-15 (10/10 days, non-empty message ids every night, so both edits
fired). The earlier "~10/day" figure was correct **for messages** and understates POSTs 2×.
Chicago runs four instances rather than five, which changes the content, never the count —
the script posts per host, never per instance.

## Current drift between live and the tracked `.example`

Diff live against `scripts/ktp-scheduled-restart.sh.example` on `origin/main`:

```diff
@@ -75,8 +75,8 @@
-CHANNEL_KTP="1458222926586446059"          # KTP Discord
-CHANNEL_EXTERNAL="1457951326666489996"     # 1.3 Discord
+CHANNEL_KTP="YOUR_KTP_CHANNEL_ID"          # KTP Discord
+CHANNEL_EXTERNAL="YOUR_EXTERNAL_CHANNEL_ID"     # 1.3 Discord
@@ -534,6 +534,9 @@
+# A quiet sweep is still not proof of health: it keys on `socket_map_`, which the
+# close callback has just emptied, so it cannot catch the recycled-fd case.
+#
```

- The **two placeholders still hold** and they are `CHANNEL_KTP` / `CHANNEL_EXTERNAL`. The
  relay secret is no longer one of them — it is sourced from `/etc/ktp/discord-relay.conf`
  at run time.
- **"live minus two placeholders" does not currently hold.** The `.example` is three
  comment-only lines *ahead* of the fleet, from the "a quiet socket-map sweep is not proof
  of health" commit, which was never deployed. Zero behavioural difference; it still means
  the guard's equality is only true modulo those lines.
- ⚠️ The copy at `N:\…\KTPInfrastructure\scripts\ktp-scheduled-restart.sh.example` in the
  shared checkout is **stale** (20763 bytes, dated Aug 4) — three commits behind. Diff
  against a fresh clone of `origin/main`, never against that tree.

## How `.example` and the guard move together

They move in **one** commit, in this order, or the guard fires:

1. Edit the live canonical on one host into a scratch copy — **not in place**.
2. Apply the identical edit to `scripts/ktp-scheduled-restart.sh.example`, keeping the two
   placeholder values.
3. `python -m pytest tests/unit/test_deploy_restart_example_guard.py` — proves the example
   still equals live-minus-placeholders before anything is deployed.
4. Land the `.example` change on `main`.
5. `python scripts/deploy-restart-script.py` from a checkout at that commit. It re-checks
   the equality against each host and refuses on drift.

The three-line comment gap above must be closed in step 2 of whichever change goes first,
or that change's diff will read as four edits rather than one.

## The proposed edit

Aim: keep the community-facing "restart in progress" notice, drop the green confirmation,
and stop paying two POSTs to say nothing.

```diff
@@ Configuration
-# Discord embed colors (matching KTPMatchHandler)
-COLOR_GREEN=65280       # 0x00FF00 - Success
-COLOR_ORANGE=16750848   # 0xFFA500 - Partial success / In progress
-COLOR_RED=16711680      # 0xFF0000 - Failure
+# Severity, glyph and colour. Deploy ktp-alert-routing.sh beside this script; a
+# partial deploy must fail loudly here, not post the wrong colour.
+. "$(dirname "${BASH_SOURCE[0]}")/ktp-alert-routing.sh" || {
+    echo "FATAL: ktp-alert-routing.sh not found beside $0 — deploy it first" >&2; exit 3; }
+COLOR_GREEN=$KTP_GREEN
+COLOR_ORANGE=$KTP_YELLOW
+COLOR_RED=$KTP_RED
+STATE_FILE="${KTP_RESTART_STATE:-/var/lib/ktp-alerts/scheduled-restart.state}"

@@ final status, around line 716
-    edit_discord_embed "$CHANNEL_KTP"      "$MSG_ID_KTP" "$FINAL_TITLE" "$FINAL_DESC" "$FINAL_COLOR" "$SERVER_NAME - $FOOTER_TIMESTAMP"
-    edit_discord_embed "$CHANNEL_EXTERNAL" "$MSG_ID_EXT" "$FINAL_TITLE" "$FINAL_DESC" "$FINAL_COLOR" "$SERVER_NAME - $FOOTER_TIMESTAMP"
+    # An edit is cheap and it is what closes out the in-progress message, so it
+    # still happens. What changes is the glyph and, on a clean night, that this
+    # is the last thing said about the run — no separate confirmation post.
+    PREV=$(cat "$STATE_FILE" 2>/dev/null | tr -d '[:space:]')
+    if [ "$FINAL_COLOR" -eq "$KTP_GREEN" ]; then
+        case "$PREV" in page|warn) SEV=recovery ;; *) SEV=info ;; esac
+    elif [ "$FINAL_COLOR" -eq "$KTP_RED" ]; then SEV=page
+    else SEV=warn
+    fi
+    ktp_alert_route "$SEV" || exit 1
+    FINAL_TITLE="$KTP_ALERT_GLYPH $FINAL_TITLE"
+    FINAL_COLOR="$KTP_ALERT_COLOR"
+    mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null && printf '%s\n' "$SEV" > "$STATE_FILE"
+    edit_discord_embed "$CHANNEL_KTP"      "$MSG_ID_KTP" "$FINAL_TITLE" "$FINAL_DESC" "$FINAL_COLOR" "$SERVER_NAME - $FOOTER_TIMESTAMP"
+    edit_discord_embed "$CHANNEL_EXTERNAL" "$MSG_ID_EXT" "$FINAL_TITLE" "$FINAL_DESC" "$FINAL_COLOR" "$SERVER_NAME - $FOOTER_TIMESTAMP"
+    ktp_alert_spool_line ktp-scheduled-restart "$SEV" \
+        "$(hostname -s): $RUNNING/$EXPECTED_RUNNING instances up" ops-daily || true
```

This **keeps** the two create-posts (lines 250–251). They are a service announcement — the
03:00 restart drops players — not a health confirmation, and silencing a community feed is
the operator's call, not a refactor's. The saving is in what the edits say, not their count.

🔴 **The one thing that must not change without checking first.** `ktp-admin-bot`'s
`cogs/ops_alerts.py` `_probe_restarts()` reads `~/log/scheduled-restart.log` over SSH — it
scans the **text** backwards for `success` / `completed` / `all servers up` against
`partial` / `failed` / `error` / `timeout`, and reads the file's mtime against
`RESTART_STALE_AFTER = 26h`. It consumes the log, never the Discord post. **Changing the
`log()` wording, the timestamp prefix, or the file's path blinds that probe, and it fails
toward "healthy"** — a log with no matching failure keyword reads as a clean run. The diff
above touches no `log()` call for exactly this reason.

## Ordering

1. Land Tier 1 and deploy `ktp-alert-routing.sh` to `/home/dodserver/` on all five hosts
   (it is sourced by path, beside the script).
2. Close the three-line `.example` gap in the same commit as the diff above.
3. Run the guard test, then `deploy-restart-script.py`, then verify md5 equality on all five.
4. Watch one 03:00. Expect: two in-progress messages per host as before, two edits per host
   whose title now carries ⚪ on a clean night, and a new local line per host in
   `/var/lib/ktp-alerts/ops-daily.jsonl`.

---

# Tier 3 — config, operator-only

⛔ **Do not invent channel ids.** Below is producer → lane. The operator maps lane → id.

## The mapping to make

Add to `/etc/ktp/discord-relay.conf` on the data server (and the `KTP_CHANNEL_*` keys to
`/home/dodserver`'s environment on the game hosts if the restart script is wired):

```sh
KTP_CHANNEL_PAGE=<id>          # must wake someone
KTP_CHANNEL_OPS_DAILY=<id>     # posts in the ops-daily lane; does not deliver the spool
KTP_CHANNEL_OPS_WEEKLY=<id>    # roll-up, read when convenient
KTP_CHANNEL_COMMUNITY=<id>     # externally visible
```

Nothing breaks if these are absent — every producer falls back to its current channel.
Set them one lane at a time and watch a cycle.

## Producer → lane

| Producer | Lane | Posts today into |
|---|---|---|
| `crashreporter` (×5 hosts) | `page` | `1497957091107668070` |
| `ktp-systemd-alert@` (`OnFailure=` on 21 units) | `page` | `1498813261263405097` |
| `ktp-data-server-health.sh` | `page` / `recovery` | `1497957091107668070` — sources the helper since 2026-09-18; falls back to this id and today's colours when the helper is not deployed beside it, and logs `severity= lane= channel= via=` on every post |
| `ktp-hltv-liveness.sh` | `page` | `CHANNEL_HLTV_STATUS` + `_EXTERNAL` |
| `ktp-backup-watchdog.sh` | `page` | `PERF_ALERT_CHANNEL` |
| `ktp-admin-bot` `ops_alerts` cog | `page` | `OPS_ALERT_CHANNEL_ID` = `1497957091107668070` |
| `ktp-fleet-health.sh` (×5 hosts) | `page` | **a raw Discord webhook, not the relay** |
| `ktp-perf-rollup` | `ops-daily` | `1497957091107668070` |
| `ktp-fleet-audit` | `ops-daily` | `KTP_ALERT_CHANNEL` = `1441291572783091793` |
| `ktp-post-reboot-verify` / `ktp-scheduled-kernel-reboot` | `ops-daily` | `1497957091107668070` |
| `ktp-scheduled-restart.sh` (×5 hosts) | `ops-daily` | `CHANNEL_KTP` + `CHANNEL_EXTERNAL` |
| `hltv-restart-all.sh` | `ops-daily` | `CHANNEL_HLTV_STATUS` + `_EXTERNAL` |
| `ktp-spike-digest` | `ops-weekly` | `1497957091107668070` |
| `ktp-soak-verify` | `ops-weekly` | `1498813261263405097` |
| `ktp-tier2-heartbeat` / `post-tier2-result` | `ops-weekly` | `1498813261263405097` |
| `precache_audit` | `ops-weekly` | `1498813261263405097` |
| `ktp-demo-retention` | `community` | `DEMO_CHANNEL_KTP` + `DEMO_CHANNEL_COMMUNITY` |

⚠️ **`ktp-fleet-health.sh` bypasses the relay entirely** — it posts to a raw
`discord.com/api/webhooks/…` URL in `/etc/ktp/fleet-health.conf` on each game host. No
relay-side routing change reaches it. It is owned by PR #391; route it there.

## Two config observations worth fixing while you are in there

- `/opt/ktp-admin-bot/.env` carries the comment `# Bot-initiated ops posts (INTEGRATION #1).
  Unset` **directly above a line that sets** `OPS_ALERT_CHANNEL_ID=1497957091107668070`.
  Anyone auditing routing from that file concludes the bot posts nowhere; it posts into the
  crash channel on a five-minute loop. The comment is stale, not the value.
- `/etc/ktp/audit.env.bak` still holds the retired channel `1081255192529477744`.

---

# Answers to the three questions this work was not allowed to assume

## 1. Is the KTP / external duplication wanted? — **Keep it. It is two audiences.**

`CHANNEL_KTP` and `CHANNEL_HLTV_STATUS` are both `1458222926586446059`;
`CHANNEL_EXTERNAL` and `CHANNEL_HLTV_STATUS_EXTERNAL` are both `1457951326666489996`. Byte
identical, and the restart script says so: `# Discord channels (same as HLTV status)`.

They are **not** two ids for one audience. Resolved against the Discord corpus channel dump
(`/opt/ktp-discord-corpus/state/guild_channels.json`, 83 channels, all
`guild_id=996884268804493363`):

- `1458222926586446059` → **`admin-audit-log`**, KTP main guild. **MEASURED.**
- `1457951326666489996` → absent from a complete main-guild enumeration, and the code
  comment reads `# 1.3 Discord`. **INFERRED** that it is the 1.3 community's own guild —
  strong, not proof: that export is a 2026-08-19 snapshot of what one token could see, so
  absence is weaker evidence than presence. `#ktp-crashes` and `#ktp-updates` are likewise
  absent and are inferred to sit in the ops guild `579024206931689482`.

One bot writes to both (`KTP Score Bot`, `1418266083873259650`). **Recommendation: leave the
pair alone.** Removing the external post would end the 1.3 community's only notice that the
servers go down at 03:00. Settle it definitively with a single `GET /channels/<id>` using the
bot token if it matters; that was out of scope here.

## 2. Is the restart volume Atlanta-only? — **No. Confirmed on all five.**

md5 `4c5297d20e01d7910a2056cfdd8ae49e` on every game host, same size, same mtime, same cron
line, and `~/log/scheduled-restart.log` shows one run per host per day for ten consecutive
days with non-empty message ids each night. The 10/day figure generalises because the hosts
are byte-identical, and that is now measured rather than assumed.

## 3. Does anything consume these posts? — **No consumer of the posts. One consumer of a log.**

- `ktp-admin-bot` runs `Intents.default()` and never enables `message_content`; the only
  grep hit for message reading is a comment asserting the absence. **No cog parses the crash
  channel.** In `KTPAdminBot` `origin/main` the channel id appears in zero files.
- `git grep 1497957091107668070` in `KTPInfrastructure` `origin/main` → 10 files, all
  producers or docs. No Discord read path exists in the repo.
- The Discord corpus does **not** cover the crash channel: 0 files for that id, against a
  positive control of 2353 corpus files and 20 `state/` channel entries on the same probe.
  It is a one-off 2026-08-19 export with no timer, not an archiver.

**So reformatting or removing a post breaks no automated consumer.** Three caveats:

1. `ops_alerts.py` consumes `~/log/scheduled-restart.log`'s **prose**. See the 🔴 note in
   Tier 2. It fails toward "healthy".
2. `#ktp-crashes` is the only durable record for several producers.
   `ktp-identity-reconcile`'s findings on 2026-09-08 survived journald rotation *only*
   because the alert had been delivered. `ktp-systemd-alert` now mirrors to
   `/var/log/ktp-systemd-alert.log` first; the crashreporter, perf-rollup and
   data-server-health do not all have that property. **Moving a producer to a quieter lane
   is not the same as giving it a durable record — do the second before relying on the
   first.**
3. `/home` on the data server was never searched for the channel id (the grep timed out on
   the demo tree and was re-run scoped to `/etc`, `/usr/local/bin` and `/opt`). A producer
   living under `/home` would not appear in any inventory here.

---

# Volume ledger

Before → after, per producer. "Messages" is what a reader sees; POSTs are HTTP calls.

| Producer | Before | After Tier 1 | After Tier 2 | Arithmetic |
|---|---|---|---|---|
| `hltv-restart-all.sh` | 4 msg/day (2 runs × 2 channels) | **0 on a clean day** | — | 2 runs × 2 channels, silent unless partial/failed or first-green-after-bad |
| `ktp-scheduled-restart.sh` | 10 msg, 20 POST/day | unchanged | 10 msg, 20 POST/day, **but the 10 edits say ⚪ not ✅** | 5 hosts × (2 creates + 2 edits) |
| `ktp-data-server-health.sh` | 22/week | unchanged (#397 owns it) | — | already transition-only; #388's deadband is merged but **not deployed** |
| `ktp-spike-digest` | 7/week, posts every run | unchanged (#393 owns it) | — | cadence change described below |
| `ktp-perf-rollup` | 0/week | unchanged | — | already silent when green |
| `crashreporter` ×5 | 0/week | unchanged | — | already silent when green |
| `ktp-soak-verify` | 0/week | unchanged | — | already silent when green |
| `ktp-tier2-heartbeat` | ~7/week | unchanged | — | already transition-only |
| `ktp-systemd-alert@` | 1/week | unchanged | — | event-driven |
| `ops_alerts` cog | unknown | unchanged | — | gateway, no log; `KTPAdminBot`#21 owns the content |

**Net measured saving from Tier 1: 4 messages/day, 28/week** — every one of which said "all
24 connected". Against a baseline of ~19 posts/day this is roughly a fifth of the volume, and
it is the fifth with the lowest information content. The rest of the reduction is in Tier 3's
routing (moving daily and weekly material out of the page channel) rather than in suppression:
**nothing else currently posts when it is green.**

## Still to do, owned elsewhere

- **Spike digest cadence** (`ktp-spike-digest.py`, owned by #393 — the cadence is free, the
  severity **floors** are not; do not re-tune them). Proposal: post daily only on a new
  fingerprint or a ≥100 ms spike, otherwise accumulate and post a Monday roll-up into
  `ops-weekly`. Estimated 7/week → ~1-2/week.
- **Disk usage/growth → a digest line, not a post** (`ktp-data-server-health.sh`, owned by
  #397). #388's deadband is merged and cuts the flip-flop; the remaining ask is that a warn
  becomes a line in `ops-daily` rather than a post in `page`. Until something drains the
  spool, that line is a local record nobody sees, so the drain has to come first.
- **AC sessions scored** — report a week-over-week delta rather than four bare integers.
- **The daily ops digest moves out of the page channel** (`KTPAdminBot`#21 owns its content;
  the channel is the operator's Tier 3 mapping).
- **`ktp-fleet-health.sh` routes past the relay** (#391).
