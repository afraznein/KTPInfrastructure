### `scripts`: compare a PR's required contexts against what reported for its HEAD sha (2026-10-10)

A **MISSING** required check and a **FAILING** one are indistinguishable from the PR
page: both render `BLOCKED`, and a missing one shows nothing red, nothing queued and
nothing waiting. On 2026-10-05 a push to a PR branch delivered no `synchronize`
event — eight of ten workflows never saw the new sha, the two that ran were
triggered by a PR-body edit (the only two whose `types:` list includes `edited`),
and two required contexts had simply never been reported. A path filter cannot
explain that shape: a workflow with a bare `pull_request:` and no paths at all also
never fired.

- `scripts/check-pr-required-contexts.py --repo <owner/name> --pr <n>` resolves the
  PR's HEAD sha, reads the required contexts off its base branch, and reports each
  as `PASSING` / `FAILING` / `PENDING` / `MISSING`.
- Exit `0` only when every required context reported success on that sha, `1` on any
  missing/failing/pending, `2` on a usage or API error, and `3` when branch
  protection is unreadable — undecidable rather than clean, so an unreadable
  required set cannot pass as an empty one.
- Each context is resolved to its **latest** attempt: the API returns superseded
  runs beside live ones, so a re-run leaves two entries per name and reading the
  first answers about whichever came back first.
- Check-runs and commit statuses are unioned. A required context produced by an
  external reporter lives at the other endpoint and reads as missing if only one is
  read.
- When something is missing the report names the remedy, which is to close and
  reopen the PR rather than `gh run rerun` — a manual re-run replays the stale
  payload against the old sha.
- `docs/CI_SETUP.md` § Before calling a PR green documents the step; the classifier
  is pure and `tests/unit/test_check_pr_required_contexts.py` exercises it with no
  network, including mutations for first-wins ordering, omitting unreported
  contexts from the verdict, and dropping the statuses endpoint.
- Not covered: `gh api` itself, pagination against a live repo, and whether a
  required context's name still matches the job that produces it. The last is
  undecidable from a checkout and reports `MISSING`, which is the useful answer but
  does not say which side is wrong. The exit-3 path is defensive and was not
  reachable on either repo tried.
