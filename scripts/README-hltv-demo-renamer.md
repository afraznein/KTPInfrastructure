# hltv-demo-renamer

Match-window-driven renamer for the always-on HLTV recording pipeline.

## Pipeline position

```
HLTV cfg `record auto_<friendly>`        produces: auto_atl1-2604292104-dod_anzio.dem
        ↓
hltv-demo-renamer.service (THIS)         produces: ktp_1777498304-ATL1_h1-2604292104-dod_anzio.dem
        ↓
ktp-organize-hltv-demos.sh @ 04:00 ET    moves to: demos/ATL1/ktp/ktp_1777498304-ATL1_h1-2604292104-dod_anzio.dem
        ↓
public portal at http://74.91.112.242/demos/
        ↓
ktp-demo-retention.sh @ 04:30 ET         deletes per-tier age (ktp/draft 180d, 12man/scrim 90d)
ktp-demo-cleanup-auto.sh every 30 min    sweeps unmatched root-level auto-*.dem >6h (retuned 2026-05-03; refuses to run while the renamer service is down)
```

## How it works

1. The service tails each game host's amxx log file (`L<YYYYMMDD>.log`) over SSH for `[KTP HLTV] MATCH_WINDOW_OPEN` / `MATCH_WINDOW_CLOSE` lines emitted by KTPHLTVRecorder v1.7.0+.
2. In-memory state tracks open match windows keyed by `(hltv_port, match_id, half)`. h1's effective close is h2's open; h2's close is the actual `MATCH_WINDOW_CLOSE`.
3. On each closed window, scans `/home/hltvserver/hlds/dod/` for `auto_<friendly>-*.dem` files whose mtime falls inside the window (with 90s padding either side).
4. Renames each matched file in place to the canonical format the existing 4 AM organizer recognizes:
   ```
   <matchtype>_<match_id>-<UPPER_FRIENDLY>(_<half>)?-<hltv_ts>-<map>.dem
   ```
5. Multi-segment matches (HLTV source-reconnect mid-half) get `_part2`, `_part3` ... appended.

## Install

```bash
# On data server as root:
cd /tmp
git clone https://github.com/afraznein/KTPInfrastructure.git
cd KTPInfrastructure/scripts
./install-hltv-demo-renamer.sh
systemctl enable --now hltv-demo-renamer
journalctl -u hltv-demo-renamer -f
```

## Operations

**Dry-run (logs renames without performing them):**
```bash
systemctl stop hltv-demo-renamer
sudo /usr/local/bin/hltv-demo-renamer.py --dry-run
# Ctrl+C when done; restart the service.
systemctl start hltv-demo-renamer
```

**Reset state (forget all open windows and log offsets — reprocess current day):**
```bash
systemctl stop hltv-demo-renamer
rm /var/lib/hltv-demo-renamer/state.json
systemctl start hltv-demo-renamer
```

**Manual rename for a known mtime + match:**
You can craft a synthetic `MATCH_WINDOW_OPEN`/`CLOSE` log line and append it to a game host's amxx log to trigger a rename. The renamer parses by content, not by filename — adding lines to any monitored log will trigger ingestion on the next 30s poll.

**Cleanup orphan auto-*.dem manually:**
```bash
DRY_RUN=1 /usr/local/bin/ktp-demo-cleanup-auto.sh   # preview
/usr/local/bin/ktp-demo-cleanup-auto.sh             # actually delete
```

## Hard prerequisites

- KTPHLTVRecorder v1.7.0+ deployed fleet-wide and active. Earlier plugin versions don't emit `MATCH_WINDOW_OPEN` / `CLOSE` log lines.
- HLTV cfgs include `record auto_<friendly>` (e.g., `record auto_atl1` in `hltv-27020.cfg`).
- Per-game-server `hltv_recorder.ini` has `hltv_friendly = <UPPER_ALIAS>` for accurate plugin chat (renamer doesn't depend on this — it derives friendly from `hltv_port`).

## Friendly-alias mapping

| HLTV port | Friendly |
|-----------|----------|
| 27020-27024 | ATL1-ATL5 |
| 27025-27029 | DAL1-DAL5 |
| 27030-27034 | DEN1-DEN5 |
| 27035-27039 | NY1-NY5   |
| 27040-27044 | CHI1-CHI5 (CHI5 currently disabled) |

## OT handling

The existing organizer regex (`(_h[12])?`) only recognizes `_h1` and `_h2` half markers — `_ot1`, `_ot2`, etc. would break the regex and OT demos would never auto-organize. The renamer strips the half marker for any half that isn't `h1` or `h2`. OT rounds remain distinguishable by their `<hltv_ts>` segment (each OT source-rotate gets a fresh timestamp).

Output for a 1st-OT-round ktp match:
- Source: `auto_ny2-2604292233-dod_anzio.dem`
- Renamed: `ktpot_1777498304-NY2-2604292233-dod_anzio.dem` (no half marker)
- Lands in: `demos/NY2/ktpot/`

If the future organizer adds `(_h[12]|_ot[1-9])?` support, drop the strip and OT round numbers will be preserved in filenames automatically.

## Failure modes

- **Game host SSH unreachable** — that host's logs aren't read this poll cycle. Resumes when SSH recovers. If down >4h, in-progress matches' windows get abandoned and the demos remain at root — **the cleanup sweep deletes root auto-*.dem at >6h (every 30 min)**, so rescue anything you care about promptly; the cleanup's renamer-active interlock does NOT protect this case (the renamer is up, the game host isn't).
- **Plugin doesn't emit MATCH_WINDOW_OPEN/CLOSE** — renamer no-ops; auto-*.dem files accumulate at root and are swept at >6h (30-min cadence). There is NO multi-day grace to manually `mv` demos — the pre-2026-05-03 7-day/daily numbers this section used to cite are long retired.
- **Rename target already exists** — skipped with warning; no overwrite. Manual operator intervention required.
- **Multi-segment with same hltv_ts** (HLTV rotation collision) — second file gets `_part2`. Vanishingly rare since HLTV's auto-suffix has minute resolution.
