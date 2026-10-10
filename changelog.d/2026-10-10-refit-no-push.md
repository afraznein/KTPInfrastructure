### The weekly refit no longer needs push rights (2026-10-10)

`ktp-map-coefficients-refit.sh` required an authenticated `gh` on the data
server so it could push a branch and open a pull request. That made dpl-e72e
wait on a credential decision nobody needed to take: the host holds a read-only
deploy key — it pulls, it does not push — and the review requirement was never
"a pull request", it was **a diff someone reads**.

Pushing is now best-effort. If push and PR work they happen; otherwise the refit
writes its proposal to `/var/lib/ktp-map-coefficients` and says so:

    map_coefficients.proposed.json   the new table
    diff.txt                         what moved
    body.md                          a ready PR body, trailer included
    0001-*.patch                     apply elsewhere with `git am`

Either way nothing is pushed to `main` and nothing is merged — the committed
table stands until a human takes the proposal to a pull request.

One thing that would have broken the automated path every week: the generated PR
body now carries `Coordination-Workstream: infra-hidden-value-plays`. The
coordination gate fails without it, so an auto-opened PR would have gone red
over a missing line.
