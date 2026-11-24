### Added
- `tests/source_anchors.py`: the shared way a guard locates code, so prose about
  the code cannot answer for it. `blank_comments` overwrites comment bytes with
  spaces rather than deleting them, which is what lets it be dropped under call
  sites that already slice by offset. `AnchoredSource.index` refuses the two
  matches that make a guard lie — one inside a comment, and one of several — and
  names each refusal as a mislocation or an ambiguity instead of returning an
  offset that means nothing. `call_sites`/`sole_call_site` answer "where is this
  called" from the parse tree, which no comment can contribute to.
- Two locating rules, because one does not fit both shapes. A definition, a
  directive or a `/**` section delimiter sits at column 0 and prose about it does
  not, so `LINE_START` is the cheapest rule prose cannot satisfy and it keeps a
  deliberate comment delimiter usable, which blanking would not. A mid-line
  expression inside a function body cannot use column 0, so `CODE` excludes
  comments instead. `body()` hands back the slice under `CODE` for that reason: a
  bare `[a:b]` returns a plain `str` and puts every assertion inside that body
  back on raw text.
- `occurrences()` for the case where several matches are there on purpose, so the
  count is asserted rather than a bare `index` quietly meaning the first.

### Changed
- `test_fleet_script_freshness.py` locates both ends of its ordering assertion
  from the parse tree. Located by text, a note naming the guard above an
  unrelated function became the match twice in a row and reported a comparison
  between two offsets that mean nothing; the second time it was the comment
  written to explain the first. The quiet half is the reason this is a guard
  rather than a cleanup: a mislocated anchor moves EARLIER, so with the other
  anchor mislocated the same assertion holds while the gate really does run
  before argument parsing, and `--help` would need the network with nothing red.
- The plugin-source guards in `test_break_scenarios.py` read `KTPBreakDrive.sma`
  through `pawn_source`, so every definition anchor must start a line and must be
  unique, and every function body is taken with `body()` rather than by offset.
  Membership asks about the code whatever the rule, since most of what code does
  is mid-line.
- Same treatment for the remaining guards whose haystack is source: the three
  `inspect.getsource(run_match)` orderings in `test_lane_b_core_ref.py`, where
  nearly half of what `getsource` returns is prose and nothing excluded it; the
  advisory-block slice and ordering in `test_lane_b_private_analytics.py`; the
  `collect()` orderings in the two capture-drift tests; and the workflow-step
  slice in `test_tier2_test_rcon_password.py`.
- `test_queue_id_command_refusal.py` keeps its `strip_comments` name and delegates
  to the shared scanner, so there is one definition of what a Pawn comment is.
  Two copies drift, and the one that drifts is the one nobody is testing.
- The two line-based locators that were already anchored at a line start now
  assert their target is unique: `next(...)` takes the first and says nothing
  about the rest, which is how a mutation edits a line other than the one the
  test names.

### Fixed
- `test_far_probe_prepares_a_real_capture_and_is_bounded_before_halftime` sliced
  `cmd_arm_kill()` as far as `bd_kill_poll()`, and `cmd_disarm_kill()` sits
  between them repeating the same lines — so the body it called `arm` held a
  function it did not name, and the ordering chain read one of two
  `remove_task(BD_TASK_KILL_POLL)` calls without saying which. Surfaced by the
  new uniqueness refusal, not by reading.
