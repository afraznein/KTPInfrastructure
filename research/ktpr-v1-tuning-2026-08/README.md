# KTPR v1 tuning research, Philly LAN 2026 (August 2026)

Historical research artifacts moved from the local `ktpeffort` checkout on 2026-09-19
(infra-ktpr-consolidation). They are the evidence behind the KTPR v1 team-formula weights
in `docs/ktpr_mcp/weights.toml`; nothing here runs in the pipeline.

| File | What it is |
|---|---|
| `KTPR_LAN_COMPARISON.md` | Old vs Current vs New KTPR over the 55 Sat+Sun tournament matches, 61 players |
| `SENSITIVITY_SWEEP.md` | One-knob-at-a-time sweep; Spearman rho vs the baseline board |
| `SWEEP_KD_BREAK.md` | `tw_kd` x `tw_break` five-variation sweep (the two master dials) |
| `NEW_KTPR_TUNING.md` | Team-formula tuning view, `[profiles.new]` levers |
| `DATA_QUALITY.md` | HLstatsX vs HUD reconciliation for the same 55 matches |
| `make_report.py`, `sweep.py`, `sweep_kd_break.py`, `tune_new.py`, `dq_report.py` | The scripts that produced the five documents |

The scripts import `ktpr_engine` / `ktpr_mysql` from `docs/ktpr_mcp/` (put that directory on
`PYTHONPATH`) and read live MySQL over SSH plus a local `roster.csv` that is deliberately not
tracked (see `docs/ktpr_mcp/README.md`). They were written against the engine as of 2026-08-07
(`ktpeffort` commit `43233dd`); the engine has grown since (per-match rows, `RawMatchStats`,
team inference), so expect small adaptations before they run again. The documents stand on
their own and are the part worth keeping.

Excluded on purpose: `roster.csv`, the season CSV/XLSX exports, and scratch `_*.py` files.
