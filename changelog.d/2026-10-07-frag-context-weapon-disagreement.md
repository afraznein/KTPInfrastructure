### Added
- `log_invariants.frag_context_weapon_disagreements()` names the one cause of a Lane B `frag_context`
  no-row that otherwise reads as unexplained frag loss: the producer publishing a different weapon
  than the engine logged for the same kill. DODX resolves a death weapon from the attacker's
  currently-held weapon, so a killer who switched or butt-killed is published under the wrong name
  and the daemon's `AND weapon IN (...)` clause matches no row. Measured at source across three
  nightly runs — producer `mp44` against engine `kar` (8->1), producer `mp40` against `kar` (11->2),
  producer `bar` against `garandbutt` (1->7). It pairs a marker only to an engine kill of the same
  killer/victim within ten seconds *before* it, because the producer buffers and the kill always
  leads; a marker with no candidate kill is a different question and is left alone, and more than
  one candidate is reported as ambiguous rather than guessed.
- `check_frag_context_diagnostics` takes those rows and names them in a failing verdict.
  **It changes no status** — the check fails exactly as before, it just stops costing a bisect of
  the whole run to learn why. `lane_b_e2e.py` also stores them under
  `report["frag_context_weapon_disagreements"]` and prints a one-line summary.

### Notes
- This is diagnosis, not the fix. The producer is the only correct home for the attribution itself,
  and the dodx/`stats_logging` half is frozen behind the schema-26 queue (`afraznein/KTPAMXX`#160).
  A daemon-side alias cannot cover it: `%fc_stock_weapon_alias` in `hlstats.pl` already maps the
  documented one-way variants (`garandbutt` -> `garand` among them) and there is no alias relation
  between `mp44` and `kar`; the broad weapon fallback that would cover it is refused in that file's
  own comment because it can steal an unrelated frag. The daemon already drops the weapon clause
  entirely for the unresolved slot it labels `mortar`, for exactly this reason — a resolved-but-wrong
  weapon has no such escape.

### Changed
- The producer startup sentinel test (`matchid "-"`, `half 0`, `sequence 0`) was inlined in
  `frag_context_diagnostic_evidence`; it is now `_is_sentinel_frag_marker` and both readers share it.
