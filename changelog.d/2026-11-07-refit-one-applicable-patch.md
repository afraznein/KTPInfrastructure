### `scripts`: the weekly refit leaves exactly one applicable patch (2026-11-07)

`git format-patch` names its output after the commit subject, and the subject
carries the run date — so every refit left its own dated patch behind, while
`diff.txt`, `body.md` and `map_coefficients.proposed.json` are fixed names that
each run overwrote. Measured on the data server on 2026-11-07,
`/var/lib/ktp-map-coefficients/` held **four** dated patches (10-15, 10-19,
10-26, 11-02) beside three undated artifacts describing only the 11-02 run.

Checked with `git apply --check` against `origin/main` that day, **three of the
four patches still applied cleanly**. So a reviewer who opened the newest diff
and applied the first patch they saw shipped a different week's refit, and
nothing anywhere reported it — the failure landed on the careful reader.

A run now moves the previous set into `superseded/before-<stamp>/` **before** it
writes its own, so no moment exists in which a new diff sits beside an old
patch. It then asserts that `format-patch` left exactly one patch, and writes a
`MANIFEST.md` naming that patch and the three artifacts that belong with it.

Three choices worth stating, because each has a wrong-looking alternative:

- **Moved, not deleted.** The commit a patch came from lives in the scratch
  worktree the `EXIT` trap removes, so the patch file is the only copy of that
  proposal. A nested `superseded/` copy is out of reach of
  `git am $PROPOSAL/*.patch`, which is what makes the wrong act impossible
  rather than merely visible.
- **Moved at the top of the run, not at the end.** Clearing at the end would
  leave the whole fit — around two hours — exposed to the mixed state it is
  meant to prevent. A fit that fails after the move leaves no patch at all,
  which is unambiguous, and the previous complete set is intact one directory
  down.
- **One `RUN_DATE`, read once.** The branch name, the commit subject and
  therefore the patch filename all carry the date, and it was read three times.
  Not reachable at the installed schedule (Mon 14:00 UTC under a 3h cap), but a
  run whose artifacts name two different days is the same ambiguity.

Eight tests, each mutation-checked: dropping the move reddens five of them and
no pre-existing test; `mv` → `rm` reddens the two that say a previous proposal
must survive; removing the one-patch assertion, the manifest, or the single
`RUN_DATE` reddens exactly its own.

**Not fixed here, and already recorded.** `diff.txt` still opens with 47 lines
of corpus-loader progress, because it is the `tee` of a single `--write` pass —
named in the 2026-10-15 fragment, with the fix being to filter the progress out
of the tee. And a map still earns a row with no minimum-halves floor: the 11-02
proposal fits `dod_railroad2_s10a` on 6 halves and `dod_anjou_a5` on 12.
