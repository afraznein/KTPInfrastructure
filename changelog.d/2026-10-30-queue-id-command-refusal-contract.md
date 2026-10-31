### `tests`: assert the 12man Queue-ID prompt refuses a chat command (2026-10-30)

The Tier-2 pin moved to the KTPMatchHandler build that added the guard, and nothing asserted the
guard. A deploy row was carried as discharged on the belief that a Tier-2 suite did.

- `tests/integration/test_queue_id_command_refusal.py` reads the pinned KTPMatchHandler source
  (`.tier2/KTPMatchHandler`, or `KTP_MATCHHANDLER_SRC`), strips comments, and asserts the ordering
  facts the 2026-10-24 ATL1 incident turned on: the prefix guard sits ahead of the sanitizer that
  strips `.`, ahead of **both** input-state branches, and behind the cancel branch that is the
  deliberate exception; the refusal tells the captain, leaves the prompt open, and leaves a log line
  carrying the input state. An unresolvable source fails under Actions and skips off it, so the
  assertion cannot retire itself.
- Red-tested in nine code directions — guard removed, `/` prefix dropped, guard moved after the
  sanitizer and after state 1, refusal resetting the state, log and chat print removed, log field
  dropped, cancel moved behind the guard — each failing only its own assertion. Two comment-only
  tampers, including one that plants a second guard inside a comment, still pass: the assertions
  read code.
- These are structural, not behavioural, and the file says so. Driving the real refusal needs a
  client in the Queue-ID input state; that state is entered only through an AMXX menu selection, the
  interception is keyed on the captain's slot, and KTPMatchHandler records that fake-client
  `engclient_cmd("say")` does not traverse the registered chat handler. A behavioural test needs a
  `KTP_TEST_MODE` rcon in KTPMatchHandler that calls `handle_13_queue_id_input` directly.
