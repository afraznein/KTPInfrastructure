### `ci`: Tier-2 gate tests the live KTPMatchHandler 0.10.185 (2026-11-12)

`tier2-integration.yml` pinned `KTP_MATCHHANDLER_SHA` to `ae69b3c` (0.10.180) while the
fleet moved through 0.10.181–0.10.185, so every Tier-2 run since built and certified a
plugin version no server runs. The pin now names `9867892` — the merge of
`KTPMatchHandler`#67, the exact commit the live 0.10.185 build was cut from — so the gate
again tests what the fleet runs. The runner's staged test build was restaged to the same
commit (`stage-runner.py`, 0.10.180 → 0.10.185).
