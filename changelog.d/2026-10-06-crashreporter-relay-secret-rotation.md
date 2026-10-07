### Fixed
- `monitoring/crashreporter/report_core.py` reads the relay secret from
  `/etc/ktp/discord-relay.conf::AUTH_SECRET` at run time and prefers it over its own
  `crashreporter.conf::RELAY_SECRET`, which is no longer required. The daemon kept a private copy;
  when the relay secret rotated into the shared conf (which `ktp-scheduled-restart.sh` had already
  been moved to sourcing for exactly this reason), that copy was left behind on all five game hosts.
  The relay answers a wrong secret with `401 {"error":"unauthorized"}` and the daemon then burns its
  five retries and abandons the core — so a crash is captured, its `.bt` is written, and **no alert
  is ever posted**. Measured on neindallas 2026-09-29: five simultaneous cores, all five
  `.reported` sidecars at `discord_posted: false` / `post_attempts: 5`, `401` on every attempt in
  the journal. `RELAY_SECRET` was byte-identical across all five hosts, so this was never
  host-specific. Startup now logs which **file** supplied the secret, never the value, and a
  disagreement between the two is warned about rather than silently resolved.
- `monitoring/crashreporter/install.sh` no longer writes a second copy of the secret when the shared
  conf already has an `AUTH_SECRET`, and `crashreporter.conf.example` comments `RELAY_SECRET` out —
  a fresh install was the other way this trap came back.

### Added
- `tests/unit/test_crashreporter_relay_secret.py` pins the precedence (shared conf wins), both
  fallback paths (shared conf absent, or present with no secret), fail-closed on neither source
  naming both in the message, and that the startup line and the disagreement warning carry the file
  and not the value. Mutation-checked in both directions: reverting the precedence to
  `setdefault` reddens the precedence test, and appending the value to the startup line reddens the
  no-leak assertions.
