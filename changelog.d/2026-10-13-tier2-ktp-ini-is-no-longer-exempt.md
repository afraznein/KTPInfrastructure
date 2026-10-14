### `scripts` + `tier2`: `ktp.ini` is no longer exempt from the runner drift check (2026-10-13)

`ktp.ini` was the one entry in `CONFIGS_RUNNER_LOCAL` whose exemption protected a
password rather than a machine credential, and it exempted the **whole file**.
The runner's copy differed from the fleet's in exactly one line —
`match_password` — so the file's other setting, and anything the fleet adds to it
later, was never compared by anything.

**What the exemption was protecting does not need protecting.** `match_password`
gates `.ktp <password>`, typed in chat; the plugin's own reply is *"Contact a KTP
admin for the match password"*, so every captain holds it. It is not `rcon`, not
a database credential, grants no shell and reads nothing. A leak lets someone
start a match on an idle server.

**And the hazard that makes a live value in a CI tree serious does not exist
here** — a fork PR running on a self-hosted runner attached to a public repo. The
workflows that run on `[self-hosted, ktp-tier2]` (`fleet-audit`,
`report-regeneration`, `tier2-integration`) trigger only on `workflow_dispatch`
and `schedule`, which need write access to the repo. The ones that do run on
`pull_request` run on `ubuntu-latest`, and `lane-b-corpus-main.yml` says that is
deliberate.

So the file joins the enumerated set: md5-compared like any other fleet config,
with `sync-runner-stack.py` clearing the alert instead of a hand copy. Each
season's password rotation now surfaces as drift **with a tool that fixes it**,
rather than diverging silently the way `ktp_maps.ini` did for 60 days.

- `test_ktp_ini_is_not_exempt` asserts it is absent from the allowlist, and
  `test_the_synced_configs_are_the_alerted_configs` now asserts it **is** written
  when it drifts. Re-adding the entry fails both rather than quietly reopening
  the gap.

⚠️ **This does not touch `audit-config-key-drift.py`'s reason for never printing
a value.** That report publishes its artifacts to a public repository and still
prints no values — not even digests — and `ktp.ini` is still named there as a
file whose values stay unprinted. Mirroring a file between two private boxes and
printing a secret into a public artifact are different acts.

⚠️ **Deploy order matters, because the two halves live in different places.**
Sync the config first, from a checkout carrying this change, then install the
updated detector to `/usr/local/bin`. Installing the detector first makes the
heartbeat page real drift for as long as the gap is open.
