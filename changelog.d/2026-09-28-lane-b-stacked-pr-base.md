### Lane B: sibling repos follow the base branch only when it exists (2026-09-28)

`lane-b-corpus-main.yml` pointed KTPAMXX, KTPHLStatsX and KTPMatchHandler at
`github.base_ref` so a run's lineage matched the PR's base. That holds for a
PR based on `main` or `preprod`, and breaks for a **stacked** PR, whose base is
a feature branch that exists in KTPInfrastructure and nowhere else: the
KTPAMXX checkout fails in twelve seconds with "a branch or tag with the name
... could not be found", which reads as the PR being broken rather than the
lineage rule not applying.

Siblings now track `preprod` when that is the base and `main` otherwise.
