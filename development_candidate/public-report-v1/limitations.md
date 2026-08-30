# Limitations and deferred work

- This is a development candidate, not a production API approval.
- Synthetic inputs prove contracts and privacy behavior, not competitive
  calibration or human norms.
- Official winner/team score is not in the current source and is not inferred.
- Real momentum-episode production still needs deterministic integration and
  human-match coverage review.
- Clip tokens need a separate authorized backend resolver and retention policy.
- Consumers remain responsible for rendering display names as escaped text.
- The serialized atomic publisher refuses non-bundle directories. Operational
  callers must choose a dedicated output directory and treat a bounded lock
  timeout as an explicit retryable failure.
- Stale-lock recovery is intentionally conservative: callers cannot configure
  a threshold below 300 seconds, and abrupt process termination is recovered
  only after that threshold expires.
- Python JSON Schema checks require `jsonschema>=4.18`; the privacy/semantic
  builder checks use the standard library.
- Spatial atlas work is explicitly deferred until artwork rights, geometry,
  contributor suppression, sparse-data, and differencing policies are approved.
- Elo, Bradley-Terry, accumulated/overall/impact ratings, and all player
  scoring remain restricted with no public DTO.
