### `scripts`: deploy-to-fleet.py reported "no credential" with the code it uses for "a push failed" (2026-11-09)

Its sibling `ktp-verify-deploy.py` was given `EXIT_NO_CREDENTIAL = 4` after the
2026-10-26 verify ended on an absent credential with nothing in the status
saying no host had been contacted. This script had the same shape from the other
end: both credential refusals raised `SystemExit` with a message, which exits 1,
and 1 is also its summary code for *at least one push failed*. A wrapper reading
the status could not tell a wave that half-landed from one that never started.

- Both refusals -- the absent SSH password, and a `$KTP_FLEET_SSH_KEY` naming a
  file that is not there -- now exit 4 and say on stderr that nothing was staged
  on any instance.
- `EXIT_OK` / `EXIT_NOT_ALL_PUSHED` / `EXIT_NO_CREDENTIAL` are named, and the
  summary exit uses them, so 1 keeps one meaning.
- The codes are in the docstring and in `--help`, which is where the sibling's
  own 2026-11-07 change established that a caller reads them.

`stage-wave.py` imports `fleet_ssh_auth` from here rather than running this
script, so an uncredentialed stage now ends 4 as well. That is deliberate and is
the same meaning; nothing documented or branched on a specific non-zero value
from either entry point.

The refusal message is ASCII. The sibling's change records a `U+2192` in help
text killing `--help` under a cp1252 stdout on the Windows workstation these
scripts are also run from, and this moves the same text onto a `print`.

`--dry-run` is unaffected in both directions: `deploy_to_instance` returns its
dry-run outcomes before `fleet_ssh_auth` is reached.
