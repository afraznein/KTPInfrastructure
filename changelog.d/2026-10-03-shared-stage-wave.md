### `scripts`: one shared, attributed `stage-wave.py` for every deployer (2026-10-03)

`stage-wave.py` assumed one operator on one workstation: a per-home ledger, rows
beside the workstation checkout, a password in that person's home and nothing
serialising two stages. Several people staging from the data server would have
split the row-flip gate and could stack two waves past the attribution gate.

- `scripts/ktp-deploy.py` (new): runs `stage-wave.py` and `ktp-wave-ledger.py`
  from a shared checkout it re-proves at `origin/main` on every run, behind a
  non-blocking lock that names its holder, against one shared ledger and rows
  file, with the person's name in `KTP_DEPLOY_ACTOR`. `stage` defaults
  `--pull-live` to a shared rollback directory. One audit line per run.
- `ktp-wave-ledger.py`: entries record `staged_by` and `reconciled_actor`; a wave
  id is claimed with an atomic `os.link`, so two stagers sharing a ledger can no
  longer overwrite each other's unreconciled wave; writes go through a temp file
  so a racing reader never sees half an entry. `status` and the gate's block
  message say who staged the wave.
- `deploy-to-fleet.py`: `fleet_ssh_auth()` adds `KTP_FLEET_SSH_KEY`, a per-person
  key used alone (no agent, no `~/.ssh` scan, no password fallback). All three
  fleet connection sites use it; unset, the password path is unchanged.
- `docs/runbooks/SHARED_STAGE_WAVE.md`: the measurements, what breaks with several
  users, the proposed install, and the decisions that are the operator's.
  Nothing is installed on any host by this change.
