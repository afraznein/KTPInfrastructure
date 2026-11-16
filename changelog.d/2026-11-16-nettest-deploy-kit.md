### ktp-nettest: deploy kit, and the node refuses a placeholder secret (2026-11-16)

- `services/ktp-nettest/deploy/` now holds everything a first node install needs: the unit with
  `ProtectHome=tmpfs`, a per-host drop-in that mounts back only each instance's `dod/logs`
  read-only (and pins the node to the housekeeping cores on the baremetals), an `install.sh` that
  is safe to re-run and never enables or starts the service, `nettest.env.example` binding
  loopback, and an nginx vhost example with buffering off in both directions.
- The node used to start with any non-empty ticket secret, including an example value. It now
  exits 2 when the secret is the example placeholder or shorter than 32 characters, and the unit
  does not restart-loop on that exit.
- The README gains a Deploy section: the install order (TLS before the site's node list), UFW,
  why a Vercel preview cannot run the test, and CPU placement.
