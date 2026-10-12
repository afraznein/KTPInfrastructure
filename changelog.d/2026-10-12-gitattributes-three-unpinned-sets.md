### Changed

- `.gitattributes` pins three sets of deployed files that no rule reached:
  `scripts/ktp-install` (python3 with no extension, so `*.py` never saw it — and
  it is the installer that writes `DEPLOYED.tsv` on live hosts), `*.timer`
  (sixteen units, sitting beside `*.service` which has been pinned all along),
  and `*.json.example` (two, beside four already-pinned `.example` kinds).
  All of them are LF on `main` today, so this changes no bytes — `git add
  --renormalize .` moves only this file. It closes the gap rather than a
  symptom: a fresh Windows clone with `core.autocrlf=true` materializes CRLF for
  anything unpinned, and the deploy then ships `\r` into systemd unit parsing or
  a python shebang. The reason to care while it is still latent is that a
  CRLF-only difference is what makes a live-vs-source md5 check manufacture
  findings — `docs/LIVE_SCRIPT_INVENTORY.md` records `/opt/lan-web` reading 31
  files "drifted" where every one was CRLF from a Windows-side deploy.
- The `config/overviews/*.txt` comment said five of the seven descriptors are
  CRLF. It is three — `dod_railroad2_s9a`, `dod_rr2_test` and `dod_schwetz`,
  measured by counting `\r\n` bytes in each blob. The `-text` rule itself is
  correct and unchanged; only the count was wrong.
</content>
</invoke>
