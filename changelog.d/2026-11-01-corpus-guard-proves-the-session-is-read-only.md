### Fixed
- `ktp-corpus-integrity-guard.sh` proves the session is read-only before it counts
  anything, instead of asserting it in a comment. `--init-command="SET SESSION TRANSACTION
  READ ONLY"` is a request: it binds the credential it is given and no other, so against a
  write-capable login it is silently ineffective. On this transport a write that SUCCEEDS
  prints nothing while a write that is REFUSED prints an error, so an absent error and a
  refusal are byte-identical -- an estate probe read that silence as a refusal on
  2026-10-21 and created a table in production. The guard now asks the server what the
  session IS (`@@session.transaction_read_only`, falling back to the pre-5.7.20
  `tx_read_only` spelling) and requires the value `1`. An empty answer is a FAILED check,
  not a quiet success, and either way it is exit `2` -- "could not look" -- which is the
  honest class for a read whose session cannot be vouched for.
- The query helper is shown to be able to report a failure at all, before its answer is
  trusted. The same `q()` is handed a statement the server cannot run and must come back
  with an error; empty there means failures are being swallowed, which would make the
  read-back above pass on nothing. Instrument first, measurement second.
- The header's `READ-ONLY. ... so the server refuses a write` sentence said the thing that
  turned out not to follow from the directive. It now names the trap instead.
- `test_it_is_syntactically_valid` passes an absolute path to `bash`, whose separators are
  eaten on a Windows dev box: that one leg was red locally while every other leg in the
  file passed, which is a red that says nothing about the guard. It takes a relative path
  and a cwd now.

### Added
- Four behavioural legs in `tests/unit/test_corpus_integrity_guard.py` that RUN the guard
  against a `mysql` double, because the test this replaces asserted
  `TEXT.count("SET SESSION TRANSACTION READ ONLY") >= 2` -- that the directive is present
  in the script, never that a session comes back read-only. A read-only session passes the
  proof and the guard completes (the positive control: without it, a proof that refused
  everything would look like a working guard); a writable session is refused before the
  corpus is read; an EMPTY answer is refused and says so; and a helper that cannot surface
  an error is refused. Mutation-checked: accepting an empty read-back fails exactly the
  empty-answer leg, dropping the discrimination probe fails exactly that leg, accepting any
  read-back value fails three, and a dead anchor outside the proof's scope leaves all
  nineteen green.
- The double's settings are exported inside `bash` rather than passed through `env=`:
  `bash` on a Windows dev box can resolve to WSL, which does not inherit the parent
  environment, and the guard then silently used its production defaults -- `/var/lib` and
  the real Discord relay conf. A test that posts to Discord is worse than no test.
