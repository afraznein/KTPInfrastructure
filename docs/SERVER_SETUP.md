# Game server setup + tuning

Moved out of the stack-root `CLAUDE.md` on 2026-07-27 to keep the always-loaded context small. **Required settings for any new or rebuilt game host.** The fleet facts needed mid-task stayed in `CLAUDE.md`: CPU core placement, the server/IP table, the paramiko SSH pattern, `.new` auto-swap, and the crash-core location.

### New Host Provisioning

Moved here 2026-08-30 from the KTP board's `TODO.md`, which was a second, drifting copy of the same
steps — this file is the named home for new-host setup. **A runbook names a LOOKUP, not a value** —
this section had already rotted twice from hardcoded values that were later moved or rotated out from
under it (see the bullet below), so every credential and key path here is a pointer to where the
current value lives, never the value itself.

**LAN venue (single all-in-one host):** use the orchestrator —
`cp provision/lan-deploy.conf.example ./lan-deploy.conf`, fill in the 3 required keys (`LAN_IP`,
`ARTIFACTS_PATH`, `LIBSTEAM_API_PATH`) plus optional bundle paths, then `sudo ./lan-deploy.sh`. Full
detail, including the day-of runbook and TeamSpeak/HLTV setup: [`../provision/LAN-DEPLOY.md`](../provision/LAN-DEPLOY.md).

**Cloud fleet (per-host, separate gameserver + dataserver):**
1. Run `provision/provision-gameserver.sh` as root.
2. Run `provision/install-linuxgsm.sh` as dodserver.
3. `clone-ktp-stack.sh` is gitignored (it can carry embedded secrets) — copy the committed template
   first: `cp provision/clone-ktp-stack.sh.example provision/clone-ktp-stack.sh`. Never commit a
   populated copy. Then run it with full options:
   ```bash
   ./clone-ktp-stack.sh /path/to/artifacts \
       --hostname <name> \
       --server-name "KTP - CityName" \
       --ip <SERVER_IP> \
       --libsteam-api /path/to/libsteam_api.so \
       --dod-base /path/to/dod-base.tar.gz \
       --sv-password <JOIN_PASSWORD> \
       --relay-url <DISCORD_RELAY_URL> \
       --relay-secret <DISCORD_AUTH_SECRET>
   ```
4. **On the data server:**
   - Append the file distributor's **current** public key to `~dodserver/.ssh/authorized_keys` on the
     new game server. Take the key path from `/opt/ktp-file-distributor/servers.json`
     (`privateKeyPath` field) on the data server — never hardcode a path in this doc. This step once
     named a fixed path directly; that key was later moved out of its original location and then
     rotated, so a host provisioned from the old, literal text got a dead key and silently received no
     distributed files. The lookup is what survives the next rotation; a value copied here would not.
   - Update `/opt/ktp-file-distributor/servers.json` with the new server entries.
   - Add the server to HLStatsX with the fleet's **current** RCON password — look it up from the
     private ops doc set (root `CLAUDE.md` § Game RCON password), do not copy the value into this
     public doc. This step once named a since-rotated value directly, which would have written a dead
     credential into `hlstats_Servers` and left the new host unable to rcon.
   - Create HLTV configs and enable systemd services for the new port range.
   - Restart `ktp-file-distributor.service` to reload config.

### UDP Buffer Configuration (Required)
Game servers generate heavy UDP traffic. Default Linux buffer sizes cause packet drops, resulting in lag and hit registration issues.

**Check for UDP errors:**
```bash
cat /proc/net/snmp | grep "Udp:" | tail -1
# Look at column 5 (RcvbufErrors; column 6 is SndbufErrors) - should be 0 or not climbing
```

**Check current buffer sizes:**
```bash
sysctl net.core.rmem_max net.core.rmem_default net.core.wmem_max net.core.wmem_default
# Default 212992 (208KB) is too small for multiple game servers
```

**Apply fix:**
```bash
# Edit sysctl.conf
sudo nano /etc/sysctl.conf

# Add these lines:
# KTP Game Server UDP buffers
net.core.rmem_max=26214400
net.core.rmem_default=26214400
net.core.wmem_max=26214400
net.core.wmem_default=26214400

# Apply changes
sudo sysctl -p

# Verify
sysctl net.core.rmem_max  # Should show 26214400 (25MB)
```

### Game Server Performance Tuning (Required)
Critical kernel and network settings for competitive game server performance. Applied to all servers 2026-04-13.

```bash
# Add to /etc/sysctl.conf:

# Disable RT throttling — SCHED_FIFO servers must never be descheduled
kernel.sched_rt_runtime_us = -1
# Prevent timer migration to isolated game CPUs
kernel.timer_migration = 0
# Disable scheduler autogroup
kernel.sched_autogroup_enabled = 0
# Only swap under extreme memory pressure
vm.swappiness = 1
# Reduce vmstat IPI frequency on isolated CPUs
vm.stat_interval = 120
# Increase NAPI budget for faster packet drain
net.core.netdev_budget = 1200
net.core.netdev_budget_usecs = 8000
# Disable unnecessary per-packet timestamping
net.core.netdev_tstamp_prequeue = 0
# No soft-lockup watchdog timers on isolated game cores (added 2026-07-02)
kernel.watchdog = 0
```

```bash
# Disable transparent hugepages (khugepaged compaction stalls; HLDS gets no THP benefit).
# Applied 2026-07-02 fleet-wide; persisted via tmpfiles.d:
echo 'w /sys/kernel/mm/transparent_hugepage/enabled - - - - never' > /etc/tmpfiles.d/ktp-thp.conf
echo never > /sys/kernel/mm/transparent_hugepage/enabled
```

**SMI check (2026-07-02):** MSR 0x34 via msr-tools (now installed fleet-wide as root). Baremetal SMI rates are benign — ATL/DAL/NYC ~0.4/hr, Denver ~0.9/hr, no active storms. SMIs ruled out as a hitreg/hiccup source on baremetals. Chicago (KVM) reports ~29/hr lifetime — guest-visible only, not actionable on a VPS. Re-check after any BIOS/firmware change: `rdmsr -p 0 0x34` twice, 60s apart.

```bash
# Disable thermald (conflicts with performance governor)
sudo systemctl disable --now thermald

# Bypass conntrack for game traffic — add to /etc/ufw/before.rules (before *filter):
# *raw
# :PREROUTING ACCEPT [0:0]
# :OUTPUT ACCEPT [0:0]
# -A PREROUTING -p udp --dport 27015:27019 -j NOTRACK
# -A OUTPUT -p udp --sport 27015:27019 -j NOTRACK
# COMMIT
```

### NTP Time Sync (Required)
Use chrony instead of systemd-timesyncd. Chrony properly sets the kernel synchronization flag that Netdata monitors, preventing false clock sync alerts.

```bash
# Install chrony (removes systemd-timesyncd automatically)
sudo apt install -y chrony

# Verify running and synchronized
systemctl status chrony
chronyc tracking  # "Leap status: Normal" = good
```

### RTC Timezone Configuration (Required)
The hardware clock (RTC) must use UTC, not local time. Local RTC causes Netdata clock sync warnings.

```bash
# Check current setting
timedatectl | grep "RTC in local TZ"
# Should show: RTC in local TZ: no

# Fix if needed
sudo timedatectl set-local-rtc 0

# Verify
timedatectl status
```

### Swap Configuration (Recommended)
Servers without swap risk OOM kills under memory pressure. Add a small swap file as safety net:
```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Firewall Configuration (UFW)
Enable UFW with rules for game servers:
```bash
sudo ufw allow 22/tcp comment "SSH"
sudo ufw allow 27015:27019/udp comment "DoD Game Servers"
sudo ufw allow 27015:27019/tcp comment "DoD RCON"
sudo ufw allow 19999/tcp comment "Netdata"
sudo ufw allow 8087/tcp comment "HLTV API"
sudo ufw --force enable
sudo ufw status
```

### Netdata Monitoring (DISABLED fleet-wide 2026-07-02)
Netdata is stopped + disabled on all five game hosts and the data server. Operator preference: query Claude directly for performance checks instead. Reason: on Atlanta, `go.d.plugin` was burning ~48% of housekeeping cpu1 (HT sibling of instance 27016's core) re-enumerating ~2,900 leaked logind sessions — jitter source for 27016/27017.

- Nodes are still claimed in Netdata Cloud (https://app.netdata.cloud) and will show as unreachable there; a one-time "node unreachable" Discord alert per node may fire.
- Re-enable on any host with `systemctl enable --now netdata` (as root).
- Data server Netdata was already stopped/unclaimed 2026-02-17.
