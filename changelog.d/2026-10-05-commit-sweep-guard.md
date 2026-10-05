### `.githooks`: refuse a commit in the shared main checkout that could sweep up another session's work (2026-10-05)

A bare `git commit` in a checkout that several sessions share commits whatever anyone else has staged, and
`git commit -a` takes every modified tracked file. `.githooks/pre-commit` refuses both in the main checkout and
allows the pathspec form (`git commit -m .. -- <paths>`), telling them apart by the index git hands the hook.
Linked worktrees skip the check. Override: `KTP_COMMIT_SWEEP=1`. Enable per clone with
`git config core.hooksPath .githooks`; `.githooks/pre-push` keeps the installed pre-push gate running, and
`scripts/hooks/install.sh` now installs into `.git/hooks` rather than following `core.hooksPath`.
