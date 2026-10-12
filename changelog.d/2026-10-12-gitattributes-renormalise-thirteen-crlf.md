### Changed

- Thirteen tracked files were CRLF on `main` and reached by no `.gitattributes`
  rule, so the pins added earlier today closed a latent gap while these stayed
  live. The pins that now reach them are — `*.env.example`, `*.cfg.example`, `*.yml`,
  `Dockerfile`, `requirements.txt`, `.gitignore` and `*.md` — and
  `git add --renormalize .` converts the blobs. **A pin alone was decorative
  here:** the blob stays CRLF until a renormalise, which is why this is a
  content change with its own review rather than something folded into the
  pin-only PR.
- The thirteen: six `build/**/Dockerfile`, `build/docker-compose.yml`,
  `build/.env.example`, `deploy/.env.example`,
  `config/lan/dodserver.cfg.example`, `deploy/requirements.txt`,
  `docs/LAN_SETUP.md` and `scripts/.gitignore`. Derived with
  `git add --renormalize .` in a throwaway worktree at `origin/main`, never read
  back from a list: the staged set is exactly those thirteen plus
  `.gitattributes`, and `git diff --cached --ignore-cr-at-eol` reduces the whole
  change to the eighteen added attribute lines — so no file's content moves.
- `config/lan/dodserver.cfg.example` is the live hazard rather than a tidiness
  point. It is exec'd by the engine after the distributor copies it, so a CRLF
  line hands a cvar a value with a trailing `\r`; its `config/online` twin was
  already LF, so the two halves of one pair disagreed. A CRLF `RUN` line in a
  Dockerfile and a CRLF `requirements.txt` both fail in ways that read as
  something else entirely.
- `docs/LAN_SETUP.md` was **MIXED**, not CRLF — 779 CRLF lines against 780 LF —
  which no diff view shows and no check in this repo flags.
- ⚠ **The commit message for `eddc8693` says *six* pins and there are seven**, listed above and
  in `.gitattributes` itself. The number was wrong in prose while the rules were
  right; it is corrected here rather than by rewriting a pushed commit, and it is
  the reason this entry now names the pins instead of counting them.
- Each pin was measured to be a no-op for every file but the intended one before
  it was added: 23 `.yml` of which 1 was CRLF, 339 `.md` of which 1 was, 7
  `.gitignore` of which 1 was, 9 `Dockerfile` of which 6 were, 5 `*.env.example`
  of which 2 were. ⛔ `*.txt` was deliberately NOT pinned — three
  `config/overviews/*.txt` descriptors are CRLF as their mapper wrote them and
  carry a deliberate `-text`; `requirements.txt` is pinned by name instead.
- ⛔ Pinning everything that counts `\r\n` bytes would have been wrong: eleven
  binaries (PNG, ICO, `.gz` fixtures) contain those bytes incidentally. Git
  already treats them as binary and the renormalise left all eleven untouched,
  which is the control.
- `tests/config_parse` reads `config/lan/dodserver.cfg.example`: 115 passed
  before the change and 115 after.
