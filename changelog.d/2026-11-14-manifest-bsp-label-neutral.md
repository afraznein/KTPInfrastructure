### `build-game-files-manifest.py`: the `maps/*.bsp` excluded-bucket label is plain wording (2026-11-14)

The label `_meta.excluded_buckets` carries for map files is served to every client with the
manifest. It described the exclusion with a rationale; it now says only what is excluded:
`maps/*.bsp (map files, not hashed by this list)`. The comment beside the bucket and the
docstrings that repeated the rationale are trimmed to match.

- Scope is unchanged: the rule, the suffix and every other bucket are byte-identical, and
  `_meta.version` (paths, hashes, alternates) does not move. The manifest file's bytes do, so
  its ETag changes and clients fetch it once more.
- The AC API keeps a compiled copy of every label (`ManifestScopeRules`) and logs
  `manifest scope DRIFT` when the served manifest's labels differ from it. The matching AC
  change has to ship in the same window as the regenerated manifest; see the PR for the order.
