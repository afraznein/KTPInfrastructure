### `scripts` + `tier2`: the runner's test-mode plugins and configs are checked by the property that matters (2026-09-28)

`ktp-tier2-stack-drift.py` covered the runner's stack binaries by md5 and its
test-mode plugins by mtime lag. mtime is not the property anyone cares about,
and measuring it produced both kinds of error at once.

A false positive, measured on 2026-09-28: the fleet's `KTPPracticeMode.amxx` had
been re-copied by a routine redistribute — 17 days of mtime, not one line of
source — and the checker had been reporting "restage it" every six hours for
days while the runner, the fleet and `origin/main` all held 1.4.9. An alert that
fires on a copy trains people to skim the one that fires on a regression.

False negatives, over the same window and invisible: `ktp_maps.ini` sat 60 days
behind the fleet while feeding match-handler map handling, `ktp.ini` sat on the
original install copy, and `dodx.ini` had never been copied to the runner at
all. Configs were excluded on a "runner-specific, cannot drift" premise — the
same premise, in the same file, that had already been wrong once about plugins.

Test-mode plugins are now compared by the **declared version, decoded out of
both artifacts** (`amxx_version.py`; `strings` on an `.amxx` returns a confident
nothing, so a decode is the only honest read). The comparison is directional:
behind the fleet is drift, ahead of it is not — a pre-activation gate is
supposed to lead, and `KTPHudObserver` is rebuilt from upstream every run so it
leads routinely. `KTPHudObserver` joins the checked set; a version that cannot
be ordered is inconclusive (exit 2), never green.

Configs are compared by md5 against the fleet, **enumerated from the fleet**
rather than from a list here, minus a named runner-local allowlist where every
entry carries its reason. Enumerating is the point: a hardcoded list cannot see
a config the fleet gains, which is how `dodx.ini` went uncopied. `hud_observer.cfg`
is in the allowlist because its absence is CORRECT — it carries the live HUD
ingest URL and key — and a test asserts it is in the shipped list, not just that
the mechanism works.

`sync-runner-stack.py` still refuses to write configs. Which of them the harness
should mirror is a judgement, not a mirror.

### `tier2`: KTPWitness is built from source per run instead of hand-staged (2026-09-28)

The witness is test-only and has no fleet counterpart, so no fleet comparison
can ever speak to it. Measured 2026-09-28: the runner held 1.7.0, built by hand
on 2026-07-04, while this repo's source had been 1.8.0 since 2026-08-25 — the
schema-22 telemetry assertions were being made by a plugin that predates them,
and every run was green.

Its source lives in this repo, so `tier2-integration.yml` now compiles and
installs it each run, the same pattern already used for `KTPMatchHandler` and
`KTPHudObserver`, and then asserts the installed artifact decodes to the
version the source declares. An empty decode fails the step rather than passing.
Staleness made impossible beats staleness detected.
