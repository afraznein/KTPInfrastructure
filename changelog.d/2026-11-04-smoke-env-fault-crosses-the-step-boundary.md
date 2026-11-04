### Fixed

- Tier 1 Smoke: the runner-environment exemption now reaches the assertion
  steps. Exempting the boot step alone was not enough — a step that exits 0
  does not stop the next one, so `Assert plugin running` still rcon'd a server
  that had never started and failed the job anyway.
