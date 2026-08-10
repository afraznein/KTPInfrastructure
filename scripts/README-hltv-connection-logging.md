# HLTV connection logging

Records connection attempts to the HLTV proxies, so that "who connected during
this match" has an answer after the fact.

## Why this exists

HLTV's own logging cannot answer it. The logging is already enabled and working
— millions of lines under `hlds/valve/` — but its vocabulary has no connect
event: it emits periodic spectator **counts** and upstream connection state,
never an identity. Measured across the retained set: **0** SteamIDs, **0**
source IPs, and no connect line shape at all.

So this is a kernel-side record, built alongside HLTV rather than from it.

> Operational context and mitigation decisions live in the private ops notes.

## Design: capture in the kernel, judge in SQL

The firewall rule deliberately **does not** try to decide which connections are
people. It logs everything reaching the proxies, capped for volume, and
`ktp-hltv-correlate.py` does the discrimination.

That split is the result of two failures, both recorded here because both looked
correct and were validated end-to-end before production falsified them:

1. **`--connbytes 200 --connbytes-mode packets`**, on the theory that "a query is
   1-2 packets, a session is thousands." True *per burst*, false *per flow* —
   `connbytes` counts a conntrack entry over its **lifetime**, so a poller
   reusing one 4-tuple accumulates past any packet threshold and then matches
   forever. **10 of 10** logged lines were one source sweeping 10 ports in 1.1s.
2. **`-m length --length 200:65535`**, to exclude query-sized datagrams. But
   `-m length` measures the packet crossing *this* hook, and the rule is in
   `ufw-before-input` on `--dport` — i.e. the **viewer → proxy** direction, which
   is command/ack traffic: measured **max 25 bytes** across 180 packets. The
   large packets are proxy → viewer and never traverse that chain. The rule
   counter sat at **0/0**; it could not fire for a real viewer, and an empty log
   is indistinguishable from a working one.

The lesson is not "pick a better threshold." It is that a kernel rule cannot be
iterated or tested here, so the fragile judgement does not belong in it. In SQL
the same question is a query you can re-run against history.

`hashlimit` holds the rule to one line per `(source, proxy port)` per hour, which
bounds a port-sweeping scanner at ~24 lines/hour instead of thousands. Loopback
is excluded — the proxies chain to each other over `127.0.0.1` and internal
plumbing is not a viewer. `LOG` is non-terminating: it records and falls through,
so the rule structurally cannot accept or drop traffic.

⚠️ Measured volume is roughly **10-25k rows/day**, overwhelmingly automated
scanners. That is the intended cost of not filtering in the kernel; it is a
trivial load for MySQL and it keeps every judgement reversible.

## Install

1. **Firewall rule** — in `/etc/ufw/before.rules`, inside `ufw-before-input`:

   ```
   -A ufw-before-input ! -i lo -p udp -m udp --dport 27020:27044 -m conntrack --ctstate NEW \
      -m hashlimit --hashlimit-upto 1/hour --hashlimit-burst 1 --hashlimit-mode srcip,dstport \
      --hashlimit-name hltvconn -j LOG --log-prefix "KTP_HLTV_CONN " --log-level 6
   ```

   Validate before reloading: `iptables-restore --test < /etc/ufw/before.rules`.
   ⚠️ `ufw reload` rebuilds ufw's own chains but does **not** flush raw `INPUT`,
   so a hand-inserted copy survives alongside the persistent one and silently
   double-logs. Check `iptables -S | grep -c KTP_HLTV` equals 1.

2. **Log routing** — `/etc/rsyslog.d/30-ktp-hltv-connections.conf` matches
   `KTP_HLTV_CONN`, writes `/var/log/ktp-hltv-connections.log` and stops. It uses
   an **RFC3339** template on purpose: syslog's default `Aug 10 11:25:01` has no
   year and no timezone, which is unparseable across a rollover.

3. **Rotation** — `/etc/logrotate.d/ktp-hltv-connections`, weekly, 26 rotations.
   ⚠️ Needs `su root syslog`: `/var/log` is group-writable, and without it
   logrotate **silently skips** the file, which reads exactly like "nothing to
   rotate yet". Verify with `logrotate -d`.

4. **Table** — `mysql hlstatsx < ../sql/ktp-hltv-connections.sql`, then confirm
   the collation actually took:

   ```
   mysql hlstatsx -e "SHOW CREATE TABLE ktp_hltv_connections\G" | grep COLLATE
   ```

   ⚠️ `CREATE TABLE IF NOT EXISTS` is a **no-op on an existing table**, so a
   table previously created with the server default silently keeps it and every
   correlation query fails with `ERROR 1267`. Only this check catches that.

5. **Ingest** — `ktp-hltv-connection-ingest.py` to `/usr/local/bin`, plus
   `cron.d/ktp-hltv-connection-ingest` to `/etc/cron.d/` (every 15 min).

## Use

```
ktp-hltv-correlate.py                    # last 30 days
ktp-hltv-correlate.py --days 90
ktp-hltv-correlate.py --ip 203.0.113.7   # still scoped by --days
```

## Reading the output

These are **connection attempts**. The columns are how you separate automation
from people, and none is a verdict on its own:

- **`ports_swept`** — distinct proxy ports this source touched within ±1h. A
  person watches one; a scanner sweeps the range. Weigh it against the rest:
  someone watching two matches in two hours also scores 2.
- **`days_active`** — distinct days this source appears at all. Pollers are
  present every day; a one-off visit is not.
- **`players_behind_ip`** — `1` means the IP has only ever carried that player,
  the strongest co-occurrence signal here. `>1` is a shared IP (VPN, household,
  venue NAT, CGNAT) and **not an identification**; one IP in this database
  carries 48 distinct players.
- **`nearest_connect`** — closest game-server connect from that IP within ±24h.
  Proximity is evidence; distance is not proof of absence.
- **No row for a person** proves *nothing*. Players average **5.3** distinct IPs
  each (max 69); any VPN or phone hotspot breaks the join silently.

A match is **co-occurrence, not intent, and not an accusation.** This is a
forensic lookup a human reads, deliberately **not** a detector.

## Verifying a change here

An empty log is the failure mode of every design so far, so never read one as
"nobody connected". Check both:

```
iptables -L ufw-before-input -n -v -x | grep KTP_HLTV   # counter must be non-zero
tail /var/log/ktp-hltv-connection-ingest.log
```

The ingest distinguishes its outcomes (`no log file matching…`, `N lines read, 0
matched…`, `log present but empty`) rather than printing one message for all of
them; the first two exit non-zero, and the empty case exits 0 because empty is
legitimately normal.
