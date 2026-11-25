### `ci`: Tier-2 gate tests the live KTPMatchHandler 0.10.187 (2026-11-25)

`tier2-integration.yml` pinned `KTP_MATCHHANDLER_SHA` to `9867892` (0.10.185) while the
fleet moved through 0.10.186 and 0.10.187. The pin now names `d69c0be`, the merge of
`KTPMatchHandler`#73 and the exact commit the live 0.10.187 build was cut from, so the gate
again tests what the fleet runs.
