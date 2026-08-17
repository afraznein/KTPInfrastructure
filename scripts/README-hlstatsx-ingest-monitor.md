# HLStatsX ingest monitor

Watches the stats pipeline for the failures that produce no error.

## Why this exists

At the Philadelphia 2026 LAN three separate defects each destroyed real data, and
not one of them raised anything at the time. The stats were only discovered to be
wrong days later, by comparing them to photographs of the scoreboard.

| What happened | Why nothing noticed |
|---|---|
| 982 kill events never reached the daemon | GoldSrc `logaddress` is fire-and-forget UDP. No retry, no error, no copy to resend. |
| Every objective capture of the weekend was discarded | `hlstats_Actions` was unseeded, and the handler skipped unresolvable actions with no `else` branch. |
| The Grand Final's second half produced events but no summary rows | A plugin bug emitted an empty match id. Nothing compared the events against the summary. |

Each check below is one of those, turned into something that fires on the day.

## What it checks

- **UDP receive-buffer drops.** The kernel's `RcvbufErrors` counter is the *only*
  evidence that log lines died in transit — there is nothing per-event to detect.
  Reports the delta since the previous run. On the production data server this
  counter is already non-zero, so the fleet is losing lines today.
- **Halves with no summary rows at all** — the empty-match-id shape.
- **Summaries short of the events they summarise.** The reverse direction is
  reported as information, not a finding: `recordEvent` only stamps `match_id`
  while the round is live, so freeze-time kills land untagged and the summary
  legitimately runs ahead.
- **Second halves far below their own first half** — partial ingest loss leaves
  plausible-looking rows rather than an obvious gap. The LAN's defective halves
  came in at 44%, 59% and 63%; every healthy one sat at 83% or above.
- **The daemon's own health line** (`KTP_HEALTH`), which reports unresolved
  actions and failed SQL writes. Requires KTPHLStatsX ≥ 0.3.5.
- **Log versus database**, with `--logs` — only possible where the game servers
  share a host with the daemon, which is the LAN case. This is the check that
  would have caught all three defects on the day.

## Install

```bash
install -m 755 hlstatsx-ingest-monitor.py /usr/local/bin/
install -m 644 ktp-hlstatsx-ingest-monitor.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ktp-hlstatsx-ingest-monitor.timer
```

A finding makes the unit fail, which fires the existing `ktp-systemd-alert`
`OnFailure` wiring and lands in Discord. That delivery path is the point — a
monitor writing to a log nobody opens is the same failure it exists to catch.

Runs as root on the data server and reaches MySQL over the local socket, so it
holds no credentials. This repository is public; keep it that way.

## At a LAN

Two changes, both because the cost of not noticing is far higher when the event
lasts a weekend and the servers go home afterwards:

1. Drop the timer to `OnCalendar=*:0/10` and add `--logs <path-to>/dod/logs` so
   the log-versus-database check runs. That comparison is authoritative.
2. Check it once after the first match of the day, by hand, before trusting it.
   `hlstats_Actions` being unseeded is a deployment mistake that only shows up
   the first time somebody captures a flag.

## Reading the output

```
  udp RcvbufErrors total=5404 InErrors=5404
HLStatsX ingest: 1 finding(s) in the last 90 minutes
  !! summary is SHORT of its events: 1785715972-KTP1 h2 -- 276 frags but only 0 kills recorded
```

Findings are prefixed `!!` and set exit 1. Lines without the prefix are context
and never fail the unit.

⚠️ A half that ended in the last 10 minutes is deliberately not checked. Without
that settle window every live match reports as broken the instant a half ends.

⚠️ The schema is two families with different collations — upstream
`hlstats_Events_*` tables are `utf8mb4_unicode_ci`, the KTP `ktp_*` tables are
`utf8mb4_0900_ai_ci`. Joining `match_id` across them raises *Illegal mix of
collations* and returns nothing, which reads exactly like a clean result. Every
join in the script pins the collation explicitly; keep it that way if you add one.
