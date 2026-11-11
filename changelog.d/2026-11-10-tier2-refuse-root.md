### `ci`: the tier-2 job refuses to run as root (2026-11-10)

`tier2-integration.yml` is the only workflow a pull request reaches, and its runner was
`User=root` on the production data server. Its first step now fails the job when
`id -u` is 0, before anything is checked out, so a runner accidentally re-installed as root
turns the required check red rather than running pull-request code as root.

`tests/unit/test_tier2_refuse_root.py` runs the step's own text from the workflow under
`bash -e` with `id` stubbed: uid 0 must exit 1 with the error annotation, uid 998 must
pass, and the step must be first. With the `exit 1` removed the root case fails.
`tests/integration/CI_RUNNER_SETUP.md` now installs the service as `ktp-tier2`, lists the
two `/etc/ktp` files it reads as `root:ktp-tier2 640`, and says to re-chown after a stack
sync.

**Merge only after the runner is re-installed as `ktp-tier2`**
(`docs/runbooks/TIER2_RUNNER_NONROOT_CUTOVER.md` § B). `integration` is a required check,
so merged against a root runner it blocks every merge on main.
