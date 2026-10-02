### `scripts`: `ktp-row-vs-box.py` checks data-server version rows against the box (2026-10-01)

The fleet-versions table records the live hash of each data-server daemon, and
nothing re-read it. `ktp-wave-ledger.py` reconciles fleet waves against the game
instances. A daemon swapped by hand on the data server reaches no ledger, so its
row could sit deploys behind with every check green.

`ktp-row-vs-box.py ROWS.md --host user@host` reads each data-server row's live
hash and the absolute path that directly follows it (`on \`/path\``), hashes that
path on the box over one read-only SSH session (md5 or sha256, by the hash's
length), and prints `OK`, `ROW_STALE`, `UNPARSEABLE`, `UNREADABLE` or
`ROW_MISSING` per row. It holds no credential: authentication is the caller's
SSH key or agent, and an unknown host key is refused.

Rows without a path, or with a `/proc/<pid>` path, are reported as unparseable
rather than guessed at. `--path COMPONENT=PATH` supplies a path for them. Row
lookup reuses `ktp-wave-ledger.py`'s first-cell matching.

Two controls run on every invocation, and a failure in either exits 2 even when
a row is stale:

- hashing a path that does not exist must fail;
- every `OK` row is re-parsed with one digit of its hash changed and must then
  read `ROW_STALE`.

Exit 0 means every row is OK, 1 means a row is stale, and 2 means the run cannot
be trusted or a row could not be checked.
