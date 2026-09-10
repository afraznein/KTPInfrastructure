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

## URGENT — capture loss on the daemon leg, unalerted

Fleet totals from `ktp_capture_health`, 2026-08-31 → 2026-09-09:

| Day | attempted | emitted | dropped | daemon_received | daemon_rejected | reject rate |
|---|---|---|---|---|---|---|
| 08-31 | 175,266 | 175,266 | 0 | **0** | 0 | — |
| 09-01 | 250,026 | 250,026 | 0 | **0** | 0 | — |
| 09-02 | 144,031 | 144,019 | 0 | 143,851 | 14,411 | **10.0%** |
| 09-03 | 170,037 | 170,017 | 0 | 169,767 | 1,888 | 1.1% |
| 09-04 | 198,671 | 198,654 | 0 | 192,426 | 2,187 | 1.1% |
| 09-05 | 136,738 | 136,712 | 0 | 136,619 | 1,869 | 1.4% |
| 09-06 | 347,833 | 347,797 | 0 | 347,002 | 2,972 | 0.9% |
| 09-07 | 187,744 | 187,722 | 0 | 187,562 | 7,849 | **4.2%** |
| 09-08 | 268,459 | 268,456 | 0 | 267,916 | 117 | 0.04% |
| 09-09 | 182,224 | 182,224 | 0 | 181,524 | 338 | 0.2% |

Three separate findings sit in that table.

**1. The producer side is clean; the loss is at the daemon.** `dropped` is 0
every day and `emitted` tracks `attempted` to within ~20 events. Every event the
game server tried to send, it sent. The gap opens between `daemon_received` and
`daemon_accepted`.

**2. `frag` is the worst-hit event type, by an order of magnitude.**

| event_type | daemon_received | daemon_rejected | reject rate |
|---|---|---|---|
| **frag** | 63,959 | **11,575** | **18.10%** |
| assist | 9,390 | 152 | 1.62% |
| life | 140,542 | 2,135 | 1.52% |
| position | 1,188,005 | 17,093 | 1.44% |
| objective_attempt | 7,563 | 75 | 0.99% |
| grenade_entity | 90,826 | 600 | 0.66% |
| team_membership | 164 | 1 | 0.61% |
| damage | 119,286 | 0 | 0.00% |
| break / flag_state / flag_position | 6,932 | 0 | 0.00% |

Nearly one frag in five is rejected fleet-wide, while `damage`, `break`,
`flag_state` and `flag_position` are perfectly clean. A uniform transport fault
would not select for one event type and spare four others.

Frags are the input to player rating. The KTPR and MMR workstreams are built on
this table's downstream products.

**3. One production server lost most of a real match.**

| Day | server | daemon_received | daemon_rejected | rate |
|---|---|---|---|---|
| 09-07 | **6 — KTP - Dallas 1** | 8,192 | 7,128 | **87.01%** |
| 09-02 | **6 — KTP - Dallas 1** | 45,232 | 13,304 | **29.41%** |
| 09-05 | 16 — KTPSCRIM New York 1 | 130,151 | 1,804 | 1.39% |
| 09-03 | 17 — KTPSCRIM New York 2 | 14,982 | 207 | 1.38% |

Dallas 1 is a production match server. The 09-07 window contains one match,
`1.3-6755-DAL1` on `dod_solitude2`, starting 21:56:06. It is intermittent rather
than ongoing — 09-08 and 09-09 are back at 0.04% and 0.2% fleet-wide — which is
worse for detection, not better: an intermittent fault with no alert is found by
noticing a number is wrong months later.

### Why this is a fault and not normal operation

By the repository's own definitions, not by inference:

- `scripts/canary_evidence.py:324-327` builds `acceptance_mismatches` from rows
  where `emitted != daemon_accepted`. Any such gap is a reportable mismatch.
- `scripts/lane_b_e2e.py:679-682` marks a frag row `report_frag_clean` only when
  `daemon_rejected == 0` **and** `correlation_failure_count == 0`. Nonzero
  rejections fail the Lane B suite.
- Rejections are expected only in the deliberately constructed diagnostic case,
  which the same file comments as "an intentional diagnostic reject".
- `duplicate_or_reordered_count` is **0 on every row**, which rules out the
  benign reading that the daemon is correctly discarding duplicates.

### What this says about coverage

`ktp_capture_health` is written on every match and read by nothing on a
schedule. No row in `ALERT_COVERAGE.md` covers it, because nothing watches it.
It is the sixth entry for that document's table of things that were detected,
recorded, and never reported — and unlike the other five, it is open right now,
three days before Season 10.

**Proposed first action** — investigation only, no fleet change:

1. Ask the operator what changed on 09-02. `daemon_received` is 0 on 08-31 and
   09-01 and non-zero from 09-02 onward: either the daemon leg started recording
   then, or it started running then. Which one decides whether 09-02's 10% is a
   regression or the first measurement.
2. Read the daemon's own log for `1.3-6755-DAL1` around 2026-09-07 21:56. A
   rejection reason at 87% will not be subtle.
3. Establish whether frag rejection correlates with `sequence_gap_count`, which
   ran 8,745 on 09-06 and 7,700 on 09-09 without a matching rejection spike —
   suggesting the two have different causes and both are unwatched.
4. Only then decide whether this is a capture bug, a daemon bug, or a schema
   mismatch rejecting valid frags.

**Then** add the alert. A capture success rate below a threshold, per match, is
one query against a table that already exists. It belongs in
`ktp-data-server-health.sh` as another state-transition check rather than as a
sixth independent alerting implementation — see §2.1.

---

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
| 1 | Investigate the capture loss | Open now, affects rating data, three days from Season 10. Investigation is read-only |
| 2 | Run `ktp-monitor-patch-check.sh` against the fleet | Built, unrun. One read-only sweep answers handover §3 Q3 |
| 3 | Capture success-rate alert | After 1 explains the cause. As a producer for the existing health check |
| 4 | Trends page in `support-web` | Data is ready and complete; this is rendering |
| 5 | Close the §2.3 drift | Live-host rollout, per-host sign-off, quiet window |
| 6 | Incident view | Real value, meaningful build, reuses 4's plumbing |
| 7 | Unify alerting | Refactor of working code. Not during the season |

Items 1 and 2 need the operator. Items 3 and 4 are ordinary repo work.

## Open questions

1. What changed on 2026-09-02 that made `daemon_received` non-zero?
2. Is the 18% frag rejection rate known, and is anything downstream already
   compensating for it?
3. Does anything read `ktp_capture_health` today other than the Lane B suite and
   `canary_evidence.py`?
4. Should the trends page be public, admin-tier, or split like the status page?
