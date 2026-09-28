### `mmr`: the operator's import stops dragging the OpenSkill solver onto the data server (2026-09-28)

`report_service import-mmr` exists so the ladder can stay in CI: it inserts a finished payload
file and recomputes nothing, which is why the data server has never held `openskill` and has no
package manager to install one. #495 then moved the methodology guards into `methodology.py`,
which builds its document out of the ladder's own constants and so imports `ladder`, and `ladder`
hard-imports `openskill.models.PlackettLuce`. The command imported it transitively and died at
`ModuleNotFoundError` before it reached the database — so the PR that made the methodology
importable is the one that stopped either payload being imported at all. The last successful run
was the day before it merged.

`AGGREGATE_KIND` and `validate_for_import` now live in `scripts/mmr/methodology_schema.py`, which
imports nothing outside the stdlib; `methodology.py` re-exports them, so the document builder and
its tests are unchanged, and `cmd_import_mmr` imports the schema module instead. A lazy import
inside the builder would have fixed the symptom while leaving `methodology` able to pull the
solver in again on the next refactor — the guards being in a file that cannot reach `ladder` is
the property, not the import order.

Held by `test_import_mmr_needs_no_solver`, which does not read the imports and judge them: it
derives from `cmd_import_mmr`'s own source what that function imports, then imports exactly those
modules in a child interpreter with `openskill` made unimportable and runs both aggregate kinds'
guards there. Re-coupling the schema module, pointing the command back at `methodology`, or
hiding the solver behind a lazy import in a callee all fail it the same way. The child also
asserts the solver really was blocked, because the whole check is vacuous on a runner that
pip-installed it — and CI installs it.
