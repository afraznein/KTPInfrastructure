### `scripts`: the manifest acknowledgement moved to the step that reaches a player (2026-09-23)

`build-game-files-manifest.py` cannot install anything. It writes a local JSON file and
stops; what changes what every player is enforced against is a separate copy onto the AC
API host, and that copy was a hand-run `scp` + `cp` pair. Both existing controls — the
advisory diff and the opt-in `--gate-scope` — sit on the local write, so the
acknowledgement was one step away from the consequence. The only control at the real step
was a convention: take a dated `.bak-<reason>` first. It is honoured in practice; nothing
enforced it and nothing compared what was changing.

`scripts/install-game-files-manifest.py` is that step. It resolves the installed manifest,
prints the scope diff, refuses unless every change it gates on is acknowledged by an exact
count, takes the backup itself, and writes atomically.

**Armed by default, which is the point of moving it.** The generator's gate is opt-in for a
good reason — a regeneration reaches nobody, so arming it by default would be friction
where nothing happens and silence where it does. Here every successful run changes
enforcement, so the default inverts. `--no-gate` is the break-glass; combining it with an
`--accept` count is rejected, because the counts *are* the acknowledgement.

🔴 **Severity gates, not just membership.** `review` → `violation` widens what a player is
scored on without adding a single path: the file was already hashed and already reported,
and the flip is what makes a mismatch count. A membership-only gate passes it, and so does
`_meta.version`, which hashes paths, hashes and alternates and not severity — so a
severity-only change leaves every version-based identity check agreeing that nothing moved.
It is not hypothetical: six lowered weapon models (`p_garand_l.mdl` and friends) went review
→ violation between the 2026-05-07 manifest and the installed one. `--accept-widened` and
`--accept-narrowed` are the counts for it, and a severity string the script cannot rank
refuses with no flag that covers it — a `.get(sev, 0)` default would have ranked a future
severity as harmless and passed on precisely the change nobody had reviewed yet.

🔴 **And allowed alternate hashes gate too, which is the worst of the three.** An
operator-curated `allowed_alternate_hashes` entry is what stops a legitimate community file
scoring. Drop one and every holder of that file becomes a violation — no path added, no
severity moved, no hash changed. The generator's diff does not compare alternates at all, so
such an install prints *"no change: same paths, same severities, same hashes"*: the single
worst case this tool exists to catch, described in reassuring words. `--accept-alternates-dropped`
and `--accept-alternates-gained` are the counts, and a change on a `review` path does not gate
because it cannot score in either direction.

⚠️ A re-hash on a path already in scope is printed and NOT gated. That is inherited from the
generator's ruling — files legitimately change on the fleet tree, and a gate that fires on
every one becomes noise and gets rubber-stamped — but the consequence is larger here, so it
is written down as a gap rather than left to be discovered.

Six separate counts rather than one total, for the same reason the generator uses counts at
all: they expire. A line pasted out of a runbook stops agreeing the moment one more path
moves, which is when someone needs to look again. Keeping them separate stops an addition
and a removal netting to zero.

The rest is the convention, made mechanical:

- the target comes from `GameFilesManifestPath` in the API's own `appsettings.json`, not
  from a path in a runbook — installing to the documented path while the API reads another
  one is an install that changed nothing and reported success;
- the backup is taken before the write and named `…json.bak-<reason>-<YYYYMMDD>`, with
  `--reason` required and sanitised so it cannot steer the file out of the directory. The
  create is exclusive (`O_EXCL`), so a name already in use gains the time rather than
  overwriting this morning's rollback copy with this afternoon's — a guarantee from the
  server rather than a directory listing, which would be a check that fails open when it
  cannot read;
- a file that exists but no longer parses is still backed up. "Is there a baseline to gate
  against?" and "is there a file I am about to destroy?" are different questions, and
  answering the second with the first would overwrite a truncated manifest — the copy you
  would most want back — with nothing kept;
- publication is a rename from a staged file beside the target, because the rename is only
  atomic within one filesystem and the API caches on mtime alone and serves whatever bytes
  are there;
- the staged bytes are read back and compared BEFORE the rename publishes them. Verifying
  afterwards detects a bad write only once the API is serving it, and `max-age=300` has
  propagated it by the time anyone reads the error; paramiko swallows the errors raised when
  closing a remote file, so the read-back is the only reliable check and it is worth nothing
  one step late;
- a file that is present but unreadable refuses outright, `--no-gate` included: it cannot be
  copied aside, so replacing it would destroy the only copy;
- a byte-identical install is declined rather than backing a file up against its own twin
  and moving the mtime the cache keys on.

⛔ The only paths written are the manifest, its backup and a staged temp beside it, every
one derived from the manifest's own name. Nothing lists, globs or operates on a directory.
`/opt/ktp-ac-api/` also holds `uploads/`, the evidence corpus, and `releases/`.

It is wired into `ktp_script_freshness` and listed in that suite's `GUARDED` set, covering
the generator beside it as well. The guard's own failure mode is this script's reason for
existing: a copy predating the severity gate would install a widening and report success,
because a check it has never heard of cannot decline. So it runs from the checkout rather
than from a `git archive` extraction — the checked version of that ritual instead of the
remembered one.

**No baseline means refuse.** With nothing installed to compare against, the generator
prints `GATE ARMED BUT NOT RUN` and writes anyway — right for a local file nobody is served.
Here that would put an unreviewed manifest in front of every player, so "could not compare"
must not read as "passed". A genuine first install says so with `--no-gate`.

Nothing changed about the generator, the manifest or what the API serves: the advisory diff
stays advisory by ruling, and installing remains an operator act. `docs/runbooks/AC_GAME_FILES_MANIFEST.md`
§5 is rewritten around the script, and `tests/unit/test_install_manifest_gate.py` pins the
arming, the severity classification, the refusals and the order of the backup and the write.
