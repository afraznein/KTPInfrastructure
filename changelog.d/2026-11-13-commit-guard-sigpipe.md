### githooks: the commit guard holds when its output is piped (2026-11-13)
- `.githooks/pre-commit` ignores SIGPIPE. `git commit ... | head -1` used to kill the hook
  with 141 when `head` closed early, and Git for Windows then committed anyway; it now exits 1
  as written. `.githooks/test-pre-commit.sh` gains a case that pipes a bare commit into
  `head -1` and requires it to be refused. Same bytes in all twelve repos that carry the guard.
