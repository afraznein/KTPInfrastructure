### Added
- `SQL` flavour in `tests/source_anchors.py`, which is what the generated-SQL
  guards needed and no existing flavour could give them. MySQL's own comment
  rules, not a generic SQL's: `--` needs whitespace after it so `a--b` stays
  arithmetic, `#` does not so `SELECT 1#x` is a comment, and `/*...*/` blanks
  whole — an optimizer hint included, because an anchor inside one is a claim
  about text the statement does not execute and being reported ABSENT is the
  loud direction. Literals are skipped entire: `-- `, `#` and `/*` inside one
  are data, and blanking them would make a guard name a selected value absent.
- A `''` branch was written for the literal scanner and then removed, because a
  mutation proved it inert and a 60,000-string fuzz found no input where it
  changed the blanking: `''` is two boundaries, so ending at the first and
  reopening at the second spans exactly what one escaped quote does. The claim
  that lived in its comment was wrong; it is a test now.

### Changed
- The ordering guards whose haystack is a statement built at run time read it
  through `code_text(..., flavour=SQL)` and `assert_in_order`:
  `test_match_retention.py`, `test_team_score_telemetry.py` and
  `test_stats_export_scope.py`. Measured first and the measurement is the
  reason the conversion is a guard rather than a repair — none of the four
  generated statements carries a comment of any kind today (0 `--`, 0 `#`,
  0 `/*` across 7,524 / 490 / 2,039 / 664 characters), and every anchor is
  unique. What changes is that a `--` line the builder grows later cannot
  answer for the statement, and a second copy of an anchor refuses instead of
  silently meaning the first.
- `test_match_retention.py` bounds the child deletes by their LAST occurrence.
  Two tables are deleted from twice — producer context, then legacy — and
  `index` took the first, so a legacy delete moved after `DELETE t FROM
  ktp_matches` left the guard green. That is not hypothetical: moving it is a
  mutation the shipped guard passes and this one fails.
- `test_stats_export_scope.py` anchors on the whole `case when match_type not
  in (...)` arm rather than on a bare `not in`. Six characters of SQL is a
  phrase a statement can grow a second copy of, and the guard would then be
  ordering on one of them while reading like a claim about the arm.
- `test_lane_b_core_ref.py` reads `lane_b_e2e.py` as Python source, so the
  ready-print/`daemon.start()` ordering cannot match a sentence about either.
  The rationale assertion beside it stays on raw text deliberately: that one IS
  a comment, and keeping the reason next to the ordering is the point.
- `test_tier2_require_sha.py`, `test_lane_b_schema_list_drift.py` and
  `test_scheduled_restart_socket_map.py` read their workflow steps and shell
  body under `HASH`. The restart script's two section delimiters ARE `#`
  comments and stay usable, since an anchor that opens with a comment marker is
  a deliberate delimiter rather than prose about one; `_slice` now delegates to
  `body()`, so uniqueness comes from the anchor type instead of two asserts the
  next slice helper would have to remember to copy.

### Not changed, deliberately
- The two orderings in `test_source_anchors.py` are raw `str.index` on purpose:
  they reproduce what an unanchored guard does, and anchoring them deletes the
  test.
- `test_ktp_tier2_stack_drift.py` orders two tokens inside an error MESSAGE.
  That is a legitimate claim about the message, not a claim about code, and no
  comment model applies to it.
- `test_assemble_changelog.py` orders headings in generated Markdown, where
  `#` is a heading and no flavour here models it — `HASH` would blank the very
  anchors. Serving it needs a comment-free flavour under `LINE_START`, for the
  uniqueness refusal alone, which is a separate change with its own reason.
