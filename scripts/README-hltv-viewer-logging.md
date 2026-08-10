# HLTV viewer-session logging

Records connections to the HLTV proxies, so that "who was watching this match"
has an answer after the fact.

## Why this exists

HLTV's own logging cannot answer it. The logging is already enabled and working
— millions of lines under `hlds/valve/` — but its vocabulary has no connect
event: it emits periodic spectator **counts** and upstream connection state,
never a viewer identity. Measured across the retained set: **0** SteamIDs, **0**
viewer IPs, and no connect line shape at all.

So this is a kernel-side record, built alongside HLTV rather than from it.

> Operational context, the threat model and the mitigation decisions live in the
> private ops notes, not here.

## Design, and the measurement behind it

The obvious rule — log `ctstate NEW` — is useless. These ports attract
continuous automated polling from server-browser and monitoring services:
measured at **75 NEW events in 240s from just 4 source IPs**, each touching ~23
of the 24 ports. That is roughly **27k lines/day** of automation drowning the
handful of genuine sessions.

The first attempt at a discriminator was **wrong, and worth recording so it is
not retried**: matching `--connbytes 200 --connbytes-mode packets` on the theory
that "a query is 1-2 packets, a session is thousands." That is true *per burst*
and false *per flow* — `connbytes` counts a conntrack entry over its whole
lifetime, so a poller reusing one 4-tuple accumulates past any packet threshold
and then matches forever. Live proof: **10 of 10 lines** the packets-mode rule
produced were a single source sweeping 10 ports in **1.1 seconds** with 33-byte
payloads.

The working discriminator is two-sided:

- **`-m length --length 200:65535`** — a query-sized datagram can never match,
  regardless of what its flow has accumulated.
- **`--connbytes 1048576 --connbytes-mode bytes`** — a flow must carry ~1 MiB
  before it is considered a session. A 33-byte poller cannot reach that before
  its conntrack entry times out; a real stream reaches it in seconds.

`hashlimit` then emits at most one line per `(source, proxy port)` **per hour**,
so a multi-hour watch produces a few rows rather than a flood. It is one row per
hour, not one row per session — do not count rows as sessions.

`LOG` is a non-terminating target: it records and falls through, so this rule
structurally cannot accept or drop traffic. That is what makes it safe to add to
a live firewall.

## Install

1. **Firewall rule** — in `/etc/ufw/before.rules`, inside `ufw-before-input`:

   ```
   -A ufw-before-input -p udp -m udp --dport 27020:27044 -m conntrack --ctstate ESTABLISHED \
      -m length --length 200:65535 \
      -m connbytes --connbytes 1048576 --connbytes-mode bytes --connbytes-dir both \
      -m hashlimit --hashlimit-upto 1/hour --hashlimit-burst 1 --hashlimit-mode srcip,dstport \
      --hashlimit-name hltvview -j LOG --log-prefix "KTP_HLTV_VIEW " --log-level 6
   ```

   Validate before reloading: `iptables-restore --test < /etc/ufw/before.rules`.
   ⚠️ `ufw reload` rebuilds ufw's own chains but does **not** flush raw `INPUT`,
   so a hand-inserted copy survives alongside the persistent one and silently
   double-logs. Check `iptables -S | grep -c KTP_HLTV_VIEW` equals 1.

2. **Log routing** — `/etc/rsyslog.d/30-ktp-hltv-viewers.conf` matches
   `KTP_HLTV_VIEW`, writes `/var/log/ktp-hltv-viewers.log` and stops, so the
   lines neither bury `kern.log` nor get lost in it. It uses an **RFC3339**
   template on purpose: syslog's default `Aug 10 11:25:01` has no year and no
   timezone, which is unparseable across a rollover and ambiguous afterwards.

3. **Rotation** — `/etc/logrotate.d/ktp-hltv-viewers`, weekly, 26 rotations.
   ⚠️ Needs `su root syslog`: `/var/log` is group-writable, and without it
   logrotate **silently skips** the file, which reads exactly like "nothing to
   rotate yet". Verify with `logrotate -d`.

4. **Table** — `mysql hlstatsx < ../sql/ktp-hltv-viewer-hits.sql`, then confirm
   the collation actually took:

   ```
   mysql hlstatsx -e "SHOW CREATE TABLE ktp_hltv_viewer_hits\G" | grep COLLATE
   ```

   ⚠️ `CREATE TABLE IF NOT EXISTS` is a **no-op on an existing table**, so a
   table previously created with the server default silently keeps it and every
   correlation query fails with `ERROR 1267`. The DDL comment cannot warn you;
   only this check can.

5. **Ingest** — `ktp-hltv-viewer-ingest.py` to `/usr/local/bin`, plus
   `cron.d/ktp-hltv-viewer-ingest` to `/etc/cron.d/` (every 15 min).

## Use

```
ktp-hltv-correlate.py                # last 30 days
ktp-hltv-correlate.py --days 90
ktp-hltv-correlate.py --ip 203.0.113.7    # still scoped by --days
```

Joins viewer IPs against `hlstats_Events_Connects` (±24h) to produce candidate
player names and SteamIDs.

## What the output means — read this before acting on a row

The join is viable because IP quality is **bimodal**. Measured: most IPs carry
exactly **one** player, but a handful carry **36-48** (VPN, shared, venue NAT),
and one infrastructure IP alone accounts for 13,885 connects from a single bot.

Every row therefore carries its own reliability markers:

- **`players_behind_ip = 1`** — real evidence of co-occurrence.
- **`players_behind_ip > 1`** — a shared IP. **Not an identification.**
- **`ports_swept > 1`** — this source touched several proxies within the hour. A
  person watches one. Treat as monitoring infrastructure whatever
  `players_behind_ip` says; the firewall rule is a filter, not a proof.
- **`nearest_connect`** — closest game-server connect from that IP within ±24h.
  Proximity is evidence; distance is not proof of absence.
- **No row for a person** — proves *nothing*. Players average **5.3** distinct
  IPs each (max 69); any VPN or phone hotspot breaks the join silently.

A match is **co-occurrence, not intent, and not an accusation.** This is a
forensic lookup a human reads, deliberately **not** a detector: the only
discriminator is viewer/player IP equality, whose false positives land on
households and shared NAT while its false negatives are free to obtain.

## Verifying a change here

Genuine sessions are rare, so an empty log proves nothing about whether the
pipeline works — and the ingest's failure modes used to be textually identical
to its success. It now distinguishes them (`no log file matching…`, `N lines
read, 0 matched…`, `log present but empty`) and exits non-zero on each, so wire
that into monitoring rather than trusting a quiet log.

To exercise the path end to end, temporarily relax the rule's `--connbytes` and
`--length` so ordinary traffic trips it, confirm lines appear with `SRC=`/`DPT=`,
then restore the thresholds and truncate the log so it holds only real sessions.
⚠️ Anything captured under relaxed thresholds is automation, not viewers —
discard it rather than ingesting it.
