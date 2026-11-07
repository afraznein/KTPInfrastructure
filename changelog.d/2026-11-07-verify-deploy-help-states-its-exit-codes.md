### `scripts`: `ktp-verify-deploy.py --help` did not show the exit-code table that tells a refusal from a verdict (2026-11-07)

The script's docstring documents five exit codes, and the point of the newest
two is that *a run which contacted no host must not look like a run that found
nothing wrong*. `--help` passed `__doc__.split("

")[0]` as its description,
so it printed the first line and nothing else: the table was reachable only by
opening the file. That truncation dates from the 2026-05-02 first cut, before
there was a table to lose.

- `--help` now carries the whole docstring, with
  `RawDescriptionHelpFormatter`, which is what four of its five sibling fleet
  scripts already do.
- The docstring is now ASCII. It is help text as of this change, and a
  `U+2192` in it raised `UnicodeEncodeError` under a cp1252 stdout -- so
  `--help` died with a traceback instead of printing, on the Windows
  workstation these scripts are also run from. Linux CI passes either way,
  which is why a test pins it rather than a convention.

No gate, default, exit code or output path moves: the codes were already
distinct, and this is about where a caller can read them.
