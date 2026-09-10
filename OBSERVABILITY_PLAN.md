# Observability plan — infra control plane

Continues the research handover
(`ktp_stats/handover/INFRA_CONTROL_PLANE_RESEARCH_HANDOVER_20260910.md`).
Measured 2026-09-10, read-only, against the repo and the live data server.

Season 10 opens 2026-09-13.

---

## Status of the handover's six items

| Item | State |
|---|---|
| §2.4 LinuxGSM patch verification | **Shipped** — `ktp-monitor-patch-check.sh`, PR #297. Not yet run against production |
| §2.6 Alert coverage matrix | **Shipped** — `docs/runbooks/ALERT_COVERAGE.md`, PR #301 |
| §2.3 Close the known drift | Detection is covered; closure needs a live-host rollout and per-host sign-off |
| §2.5 Trend surface | **Researched below. The handover's guess was right, and one finding is urgent** |
| §2.2 Incident view | Planned below |
| §2.1 Unify alerting | Planned below, still last |

Two things landed that the handover did not scope: the access map
(`docs/runbooks/FLEET_AUDIT_ACCESS.md`) and the audit workflow
(`.github/workflows/fleet-audit.yml`, PR #302), which fixes the reason a merged
check was not a running check.

---

## §2.5 — the data is already in MySQL, and it is better than expected

The handover said: *"This may be a query-and-render problem, not a
metrics-pipeline problem — worth checking before anyone installs Prometheus."*

Checked. It is a query problem. Nobody should install Prometheus.

### Performance trends: complete, fleet-wide, 4.5 months

| Table | Rows | Range | Coverage |
|---|---|---|---|
| `ktp_telemetry_metrics` | 785,585 | 2026-04-25 → 2026-09-10 | **139 distinct days across a 139-day span** |
| `ktp_telemetry_baselines` | 2,798 | 2026-05-01 → 2026-09-09 | 131 days, per server per day |
| `ktp_spike_daily` | 7,576 | 2026-07-10 → 2026-09-10 | 63 days |
| `ktp_matches` | 4,219 | 2026-01-18 → 2026-09-09 | 8 months |

139 distinct days over a 139-day window means **zero gaps**. Per-day server
coverage is `MIN = MAX = 24` — every one of the 24 instances reported on every
one of those days. This is a cleaner dataset than most purpose-built metrics
pipelines produce.

`ktp_telemetry_metrics` already carries `fps_p50/p95/p99`, `fps_stddev`,
`fps_min/max`, `fps_sample_count` and per-phase spike counters
(`spike_phys/read/steam/send`) per `server_endpoint` per window.
`ktp_telemetry_baselines` already rolls that to a day with mean, stddev, a
computed baseline and `warn_fps` / `warn_spikes` flags.

`TEST_INFRASTRUCTURE_PLAN.md:212` deferred "MySQL-backed Grafana dashboard for
30-day trends per server per phase" pending whether Grafana was in the stack. It
is not, and it is not needed: the aggregate the dashboard would have drawn is a
`GROUP BY` away, and the site that would render it already exists in
`sites/support-web/`.

**Proposal.** Add a tier-gated trends page to `support-web` rather than standing
up Grafana. It reads MySQL directly, reuses the existing Discord OAuth and
`app/tiers.py` gating, and matches the design already there. No new service, no
new daemon, no new port, no new credential. Renders per-server FPS percentiles
over 30/90 days and spike counts per phase.

### Capture health: young, partial, and already telling us something

`ktp_capture_health` is per-match, not per-day. Its grain is one row per
(match-half, event type): 2,859 rows over 136 matches, 265 match-halves and 11
event types, 2026-08-31 → 2026-09-09. It carries
`attempted`, `enqueued`, `dropped`, `emitted`, `daemon_received`,
`daemon_accepted`, `daemon_rejected`, `sequence_gap_count`,
`duplicate_or_reordered_count` and `correlation_failure_count`.

So the handover's framing — *"is capture success rate degrading across the
season"* — cannot be answered for past seasons; the instrument is younger than
the question. It **can** be answered for Season 10 from its first day, which is
what matters going forward.

It also already has an answer for the ten days it does cover, and that answer is
the urgent part of this document.

---

## Capture loss — mostly fixed on 2026-09-08, frag alone still failing

**This section was revised after the operator proposed a daemon-restart
explanation. They were substantially right, and the first version of this
document mis-attributed the cause.** What follows is the corrected reading.

### The fix is real and it is dated

`hlstatsx.service` last started **2026-09-08 16:34:28 EDT**, `NRestarts=0`.
Everything after that timestamp:

| event_type | daemon_received | daemon_rejected | rate |
|---|---|---|---|
| life | 33,634 | **0** | 0.00% |
| damage | 28,576 | **0** | 0.00% |
| position | 290,024 | **0** | 0.00% |
| assist | 2,311 | **0** | 0.00% |
| objective_attempt | 1,674 | **0** | 0.00% |
| break | 374 | **0** | 0.00% |
| flag_state | 986 | **0** | 0.00% |
| flag_position | 253 | **0** | 0.00% |
| team_membership | 27 | **0** | 0.00% |
| **frag** | **15,444** | **405** | **2.62%** |

Nine of ten event types are at exactly zero across 357,859 events. The restart
fixed the broad loss completely. Frag is the sole survivor.

### What the broad loss was

Fleet-wide frag rejection ran 22-34% from 09-02 through 09-06, then 9.7% on
09-07, 1.1% on 09-08 and 4.8% on 09-09. The single worst case,
**Dallas 1 at 87.01% on 2026-09-07** (7,128 of 8,192) during match
`1.3-6755-DAL1`, belongs to this era.

The first version of this document read that 87% as part of the frag story. It
was not: Dallas 1's loss was spread across every event type it produced
(`team_membership` 25.0%, `assist` 18.7%, `life` 17.2%, `position` 16.0%,
`frag` 14.4%, `objective_attempt` 10.3%, `grenade_entity` 9.0%). It was a broad
daemon-side failure, and it is gone — Dallas 1 has run at 0.18% and 0.20% on
09-08 and 09-09.

Two problems were being read as one. The restart killed the larger one.

### What is left, and why it still matters

Frag rejection post-restart is **2.62%, and it is bursty rather than uniform**.
On 09-09, two matches account for 285 of the 405 post-restart rejections:

| Window | Match | server | frag received | rejected | rate |
|---|---|---|---|---|---|
| 16:41-17:22 | `1.3-6770-NY1` | 16 | 692 | 148 | **21.39%** |
| 17:30-18:12 | `1788989435-NY2` | 17 | 555 | 137 | **24.68%** |

Every other post-restart match sits between 0.00% and 0.85%. The match
immediately before that pair (`1.3-ready-NY1`, 15:41-16:24) was 0.18%, and the
one after (`1788994384-NY1`, 18:53-19:36) was 0.48%.

**A concurrency explanation was tested and rejected.** The two bad matches ran
sequentially, not simultaneously — NY2 started 17:30:41, after NY1 ended
17:22:52. Meanwhile `1.3-6774-ATL1` (20:54-21:14) and `1789002669-ATL2`
(21:11-21:31) genuinely overlapped on one host, 74.91.121.9, and came in at
0.55% and 0.37%. Two concurrent matches on one host is not the trigger.

What is left is a roughly 90-minute window, 16:41 to 18:12 on 2026-09-09, in
which whichever match was running lost about a quarter of its frags. Both
affected servers sit on 74.91.123.64, but no other host ran a match in that
window, so host-scoped and fleet-scoped cannot be distinguished from this data.

### Why frag, and why it matters more than the percentage suggests

Frags are the input to player rating; KTPR and MMR are built downstream. A 2.62%
average that arrives as a quarter of one match's frags is worse than a flat
2.62%: it corrupts specific matches badly rather than adding uniform noise that
averages out.

By the repository's own definitions this is still a fault, not tolerable noise:
`scripts/lane_b_e2e.py:679-682` marks a frag row clean only at
`daemon_rejected == 0` **and** `correlation_failure_count == 0`, and
`scripts/canary_evidence.py:324-327` treats any `emitted != daemon_accepted` gap
as a reportable mismatch. `duplicate_or_reordered_count` is 0 on every row, so
this is not the daemon correctly discarding duplicates.

### Does this hold for Season 10

For nine event types, yes — zero rejections across 357,859 post-restart events
is strong evidence. For frag, the honest answer is **not yet demonstrated**: the
post-restart record is two days long and contains one ~90-minute window that lost
a quarter of its frags.

The cheap way to know is to look again rather than to argue about it. The
proposed check below answers it per match, automatically, from a table that
already exists.

### What this says about coverage

`ktp_capture_health` is written on every match and read by nothing on a
schedule. No row in `ALERT_COVERAGE.md` covers it. A daemon-side fault ran for
at least six days, cost one match 87% of its events, was recorded in full
detail, and was found only because someone went looking for a trends dataset.

**Proposed check.** Per-match capture success rate, as a producer for
`ktp-data-server-health.sh` rather than a sixth alerting implementation. Alert
when any match's per-event-type rejection rate crosses a threshold. It is one
query against a table that already exists, and it would have caught both the
broad loss and the residual frag bursts on the day.

**Proposed investigation**, read-only, no fleet change:

1. Read the daemon log for 2026-09-09 16:41-18:12 and for match
   `1.3-6770-NY1`. A 21% rejection rate will name its own reason.
2. Establish what the daemon rejects a frag *for*, and whether that reason is
   reachable when the other ten event types are not being rejected at all.
3. Confirm whether the 09-08 16:34 restart picked up new code or simply cleared
   accumulated state. That decides whether the broad loss can return.

## §2.2 — incident view

The handover's case for this is now concrete rather than hypothetical.
`ktp-identity-reconcile.service` has been failed since 2026-09-08 09:01:53 EDT.
Its `OnFailure=` alert fired successfully at that timestamp. Two days later the
unit is still failed. Detection worked; nothing tracks whether a delivered alert
was acted on.

The state already exists, scattered:

| Source | Holds |
|---|---|
| `/var/lib/ktp-data-server-health.json` | current down-set, transitions |
| `/var/lib/ktp-audit-state.json` | repo-drift keys, new vs resolved |
| `ktp-hltv-liveness.sh` state file | `FAILS`, `LAST_ALERT` |
| `ktp-tier2-heartbeat.sh` state file | `prev_alert` |
| `ktp_telemetry_baselines.posted_to_discord` | perf alert dedup, in MySQL |
| `systemctl --failed` | live failed units |

Nothing joins them, so no surface answers "what is broken right now, and since
when."

**Proposal.** A second `support-web` page, admin-tier, that reads those sources
and renders open-versus-resolved with a time-since column. Read-only first: no
acknowledgement workflow until the read-only version has proven it shows the
right things. Sequence it after the trends page — same site, same auth, same
tier gating, and the second one is mostly the first one's plumbing again.

The GitHub issue opened by the audit workflow covers this for drift
specifically. This page covers the rest.

---

## §2.1 — unify alerting

Still last, and the handover's reasoning holds: five working implementations,
none on fire, refactored during a live season is a bad trade.

What has changed is that the case is now sharper. The alert coverage matrix
found that adding a sixth check today means writing a sixth state machine, and
this document proposes exactly one new check (capture success rate). That check
should be a producer for `ktp-data-server-health.sh`, which already owns
state-transition alerting and already alerts on the right channel per the
2026-05-06 operator decision — not a new script with its own state file.

Rule to hold to until §2.1 is properly scoped: **no new alerting
implementations.** New checks become producers for an existing one.

---

## Sequencing

Conservative, and shaped by what is live rather than by what is elegant.

| # | Item | Why here |
|---|---|---|
| 1 | Investigate the residual frag loss | Nine event types fixed by the 09-08 daemon restart; frag alone still bursting to ~22-25% on some matches. Read-only |
| 2 | Run `ktp-monitor-patch-check.sh` against the fleet | Built, unrun. One read-only sweep answers handover §3 Q3 |
| 3 | Capture success-rate alert | After 1 explains the cause. As a producer for the existing health check |
| 4 | Trends page in `support-web` | Data is ready and complete; this is rendering |
| 5 | Close the §2.3 drift | Live-host rollout, per-host sign-off, quiet window |
| 6 | Incident view | Real value, meaningful build, reuses 4's plumbing |
| 7 | Unify alerting | Refactor of working code. Not during the season |

Items 1 and 2 need the operator. Items 3 and 4 are ordinary repo work.

## Open questions

1. Did the 2026-09-08 16:34 restart of `hlstatsx.service` pick up new code, or
   just clear accumulated state? That decides whether the broad loss can return.
2. What does the daemon reject a frag *for*? Nine other event types are now at
   exactly zero, so whatever the reason is, it is frag-specific.
3. Are the matches from 09-02 to 09-08 that lost 22-34% of their frags going to
   be re-ingested, corrected, or accepted as degraded?
4. Does anything read `ktp_capture_health` today other than the Lane B suite and
   `canary_evidence.py`?
5. Should the trends page be public, admin-tier, or split like the status page?
