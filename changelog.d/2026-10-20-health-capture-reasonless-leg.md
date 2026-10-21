### Added
- `ktp-data-server-health.sh` grows a third capture leg, **`capture-half-reasonless`**: a
  `(half, event_type)` stream in the trailing 24h that refused events and recorded no reason for
  refusing them. Warn 1, up to three streams named in the body, and the hourly line also names the
  reason behind the most refused events — so a cause reaches the page and not only the row.
  `ALERT_COVERAGE.md` carries the row.

  This is the assertion for the defect migration 044 and `afraznein/KTPHLStatsX`#166 fixed: every
  rejection site computed the reason as its dispatch status string, tested it to decide the marker
  was refused, then discarded it, so a lost half was pageable and not diagnosable. Nothing on the box
  watched for the state recurring.

  Measured read-only on `hlstatsx` 2026-10-20, which is what makes warn 1 reachable rather than
  guessed: of **623** rejecting half-streams written before the 10-13 17:40 ET daemon swap, **623**
  record no reason — the leg would have fired on every one of them — and of **49** written after,
  **0** do. No non-rejecting row carries a reason either, so the column tracks refusal exactly.

  ⛔ Its query is deliberately separate from the two existing legs rather than a column added to
  theirs. Folding `rejection_reasons` into those would let a missing column fail the loss leg
  outright, and the reason for a loss must never be able to hide the loss. When the column is absent
  the lookup degrades to one line saying the leg is BLIND and latches nothing — a new alert should
  not be the first thing to discover a migration was never applied.

  ⚠️ `mysql -N -B` prints a NULL as the four characters `NULL`, so the reducer treats that spelling
  and an empty field alike; a reducer testing only for emptiness scores a NULL column as a recorded
  reason, which is the original defect reported clean. A mutation dropping either spelling turns
  `tests/unit/test_health_capture_half.py` red.
