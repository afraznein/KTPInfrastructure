# Adding a map to the fleet

From "a new `.bsp` landed" to "the map is on all 24 instances and FastDL serves it".

The build half is one command and is safe to run anywhere. The deploy half is the
operator's, touches production, and is where every hazard in this document lives.

---

## 1. What a deployable map is

Four files, and a client needs all four:

```
maps/<map>.bsp          the map                       (given)
maps/<map>.res          what the client must download (RESGen)
overviews/<map>.txt     spectator overview descriptor (make_overview_descriptor.py)
overviews/<map>.bmp     spectator overview image      (render_overview_bmp.py)
```

⚠️ **All four are keyed on the stem, so when a published schedule name and the built `.bsp` disagree,
move the schedule row — do not rename the map.** A rename drags the overview pair and the stem-fetched
`.res` along with it.

`maps/<map>.txt` is **not** required. It is an optional briefing file; most maps
on the fleet do not have one. Do not invent one.

The `.res` is the file that matters most and fails most quietly. It lists every
model, sound, sprite, skybox face and WAD the map needs. A `.res` that omits a
`.mdl` gives the client a map with missing props — or, on some code paths, a
`Mod_LoadModel` `Sys_Error`, which is how ATL1 went down on 2026-05-11. A `.res`
that omits a sound gives silence. Neither logs anything: the map just reads as
broken.

### A map already in the pool already has its pair — do not go looking for art

⛔ **This section builds the pair for a NEW `.bsp`. It is not an invitation to source one for a
map the league already plays.** Every stem the live pool binds already ships a `.txt`/`.bmp`
pair: ours, authored here (the descriptors say so), carrying real `ZOOM`/`ORIGIN`/`ROTATED`,
and already in every place that serves one — FastDL, the data-server docroot,
`/home/dod/distribute/overviews`, the game hosts and the local staging tree, md5-identical.

🔑 **An asset-sourcing hunt was run and the answer was that there was nothing to source.** The
premise it refuted — *"Steam ships stock maps only and no overview was found for the custom
pool"* — described a search, not the world: the pairs are not Steam's. **That is the kind of
answer that gets re-opened as a work item**, so it is written here rather than left in a
measurement nobody can find.

➡️ **Re-derive it rather than trusting this paragraph.** Take the stems from the seasonal
section of `config/local/ktp_maps.ini` (a copy of the owner's file in
`afraznein/KTPDoDServerConfig`, which is what the fleet loads), then probe both halves:

```bash
curl -sI https://fastdl.ktpdod.com/dod/overviews/<stem>.txt   # expect 200
curl -sI https://fastdl.ktpdod.com/dod/overviews/<stem>.bmp   # expect 200
```

⚠️ **A RETIRED stem still answers 200, so a probe built on a stale map list passes and
certifies coverage the pool does not have.** FastDL keeps superseded revisions: predecessors of
current pool maps answer `200` on both halves long after nothing binds them. **Derive the stem
list; never type one from memory**, and carry a nonsense stem as the `404` control so a probe
that answers 200 for everything is visible as one.

## 2. Build the bundle

Build RESGen once (it is GPL-2.0 third-party code and is not vendored here):

```bash
scripts/build_resgen.sh              # clones + builds at the pinned 2.0.3 tag
export KTP_RESGEN=~/.cache/ktp/resgen/bin/resgen
```

Then, per map:

```bash
python scripts/build_map_bundle.py /path/to/dod_newmap_b1.bsp \
    --out ~/staging/s11-maps \
    --compare-against /path/to/previous/res/dir --predecessor dod_newmap_a9
```

That produces the four files plus `MANIFEST.json` (md5 and size of each), prints
the entry-list delta against the predecessor, and exits non-zero if the `.res`
fails its self-check. Run it once per map into the same `--out`; the manifest
accumulates.

**Read the delta.** An added or removed `.wad` should match a change in the BSP's
worldspawn `wad` key, which the tool prints next to it. An added or removed
`.mdl` should match a prop the mapper added or removed. A delta you cannot
account for is a finding, not a formality.

If the overview scripts are not yet on `main` (they arrive with
`KTPInfrastructure` PRs #395 and #396), render the pair separately and pass
`--overviews-from <dir>`.

### Ordering is load-bearing

RESGen lists `overviews/<map>.txt` and `.bmp` **only if both already exist** next
to the map when it runs. Render the overview first. Ten of the eleven
disagreements in the 44-map replay of the fleet's existing `.res` corpus were
exactly this — a `.res` generated on one side of its overview's existence, with
nothing anywhere reporting the omission. `build_map_bundle.py` enforces the
order and fails the bundle if the pair is missing from the entry list.

### Line endings

The tool writes CRLF, because all 47 `.res` files already on the fleet are CRLF
(they were generated on Windows). `--line-endings lf` exists; there is no fleet
evidence for it, so leave it alone.

## 3. Verify before deploying

```bash
scripts/validate-map-assets.sh --maps-dir <a dod/ tree with the bundle dropped in> <map>.bsp
```

This is the pre-flight that catches the crash class: it walks the `.res` and the
BSP strings and reports assets that are not on disk. Exit 1 means at least one
`.mdl`/`.spr` is missing — do not deploy.

## 4. Deploy — operator only

### 4a. The game servers

`/home/dod/distribute/` on the data server is a **live deploy path**.
`ktp-file-distributor.service` pushes anything created or changed there to all 24
instances within about 15 seconds.

- ⛔ **It syncs deletions.** An `rm` in `distribute/` removes the file from all 24.
  Never `rm` or `mv` there; write with `cat new > file`, and keep backups outside
  the tree entirely.
- ⛔ **Build the bundle outside `distribute/` and copy it in.** Editing in place is
  the deploy.
- ⚠️ **The distributor pushes on CHANGE and never back-fills.** A file that is
  already sitting in `distribute/` was pushed when it landed there and will not be
  pushed again. "It is in `distribute/`" is not evidence a host has it — Atlanta
  was found missing 123 files for exactly this reason.

### 4b. FastDL

The game servers having the files is only half of it. Clients fetch from
`https://fastdl.ktpdod.com/dod/` (uniform on all 24 since the 2026-09-09
rollout), so the assets must also be on the FastDL docroot.

- Canonical path is `/var/www/fastdl/dod/<game-relative-path>`. The engine
  prepends `dod/` to every request, so a file one level too high exists on disk
  and 404s for every client.
- ⚠️ **A WAD lives at `/dod/<name>.wad`, not under `maps/`.** A new map that pulls
  in a WAD the fleet has never served before needs that WAD uploaded to the
  docroot root, not beside the `.bsp`.
- Check a path with `curl -sI https://fastdl.ktpdod.com/dod/<path>` — and read the
  status, not a redirect chain (`curl -L` reports the final URL's status).
- ⚠️ Watch for HTTP/2 truncation on busy evenings: a truncated `.wad` is written
  to the client's disk and never re-verified, so it becomes permanently missing
  textures with no error anywhere.

### 4c. Activation

A map does not need a restart to become playable — but nothing here should be
taken as licence to restart anything. **Never restart a game server without
explicit permission.**

## 5. Verify after deploying

Two separate questions, and the second is the one that gets skipped.

**Is it there?** On every one of the 24 instances, not one:

```bash
md5sum ~/dod-<port>/serverfiles/dod/maps/<map>.{bsp,res} \
       ~/dod-<port>/serverfiles/dod/overviews/<map>.{txt,bmp}
```

Compare every hash against `MANIFEST.json` from the bundle. ⚠️ **Check all 24.**
A single-host check generalises wrongly; assuming one host's state held for the
fleet produced three wrong answers in one session. Drive it from `ktp_hosts.py`
(`FLEET` + `PORTS`), and treat a failed command as a failure, never as a zero.

**Is FastDL serving it?** `curl -sI` each of the four paths plus any new WAD, and
confirm `200` and a `Content-Length` matching the manifest's `bytes`.

⚠️ **The two questions are not interchangeable, and the host-side one is the half that
fails silently.** Clients fetch overviews from FastDL, so a player sees a correct overview
on a host holding neither file — only the server-side spectator path reads the host's own
copies. **A clean FastDL probe and a match nobody complained about are both consistent with
a host that is missing the pair**, which is how a region can run degraded spectator
overviews for weeks with no symptom anyone would report.

✅ **That gap is covered standing, so it does not have to be a habit.**
`scripts/audit-distribute-drift.py`, run weekly by the **Fleet Audit** workflow, takes its
scope from the distributor's live `WatchPatterns` — which carry `*.bmp` and `*.txt`, so every
pair under `/home/dod/distribute/overviews` is in it — and reports `shape=absent` for a path
that is on no instance. ⛔ **Its invariant is source-to-instance, not pool coverage:** a pair
deleted from the source syncs as a deletion to all 24 and then reads as no drift at all.
Shapes and triage: `docs/runbooks/DISTRIBUTE_DRIFT.md`.

---

## Where the RESGen numbers came from

`build_resgen.sh` pins the `2.0.3` tag rather than `master` or `2.0.2`. What that
rests on, measured 2026-09-15 against the Dallas `dod-27015` tree:

- 44 maps on the fleet carry a RESGen-generated `.res`. All 44 were regenerated
  from their own BSP and compared entry-by-entry against the shipped file.
- **43 of 44 reproduced the shipped non-overview entry list exactly, in order.**
  Zero models, sounds, sprites, skybox faces or WADs were added or dropped on any
  map. The one exception is `dod_anzio3_b1.res`, which lists
  `models/mapmodels/ivy5.mdl` while its BSP contains no reference to it at all —
  that file was edited or generated from a different BSP, not a generator
  difference.
- Eleven maps differed once overviews were counted. Ten are the overview pair
  present or absent on disk at generation time; one (`dod_anjou_a4`) has the pair
  appended after the sorted block, which is what a hand-append looks like.
- Tags `2.0.2` and `2.0.3` produce **byte-identical** output on all 44 once the
  version string in the header comment is masked. 2.0.3's only changelog entry is
  the opt-in `-n` flag; the skyname/WAD parsing fix is 2.0.2's, so it is already
  in the fleet corpus.
- `master` is 58 commits past the `2.0.3` tag, includes a behaviour change
  ("Add parsing for wav files in sentences"), and **still reports
  `RESGen version 2.0.3`**. The banner cannot distinguish them. Pin the ref.
- Tag `2.0.2` does not compile on a modern toolchain without a `_stricmp` shim;
  the fix landed between the two tags. The reference build used for this
  comparison carried that one-symbol define and nothing else.
