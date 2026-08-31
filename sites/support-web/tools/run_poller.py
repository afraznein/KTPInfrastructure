#!/usr/bin/env python3
"""Poll the fleet once and write the status documents. Run by a systemd timer.

One-shot rather than a daemon: a crashed daemon leaves a stale JSON that reads
as a healthy fleet, whereas a timer that stops firing leaves the same stale JSON
but is visible in `systemctl list-timers`. The page treats an old `generated`
stamp as unknown either way -- see STALE_AFTER in the status route.

Exit codes: 0 wrote both documents, 1 could not write. A fleet that is entirely
down is still a successful poll -- that is a real result, not an error.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import poller as P  # noqa: E402

PUBLIC_DEFAULT = "/var/www/support.ktpdod.com/status/public.json"
DETAIL_DEFAULT = "/var/lib/support-web/detail.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--public", default=os.getenv("SUPPORT_PUBLIC_JSON", PUBLIC_DEFAULT),
                    help="served to anyone; allowlisted fields only")
    ap.add_argument("--detail", default=os.getenv("SUPPORT_DETAIL_JSON", DETAIL_DEFAULT),
                    help="operator view; MUST live outside the web root")
    ap.add_argument("--dry-run", action="store_true", help="print instead of writing")
    args = ap.parse_args()

    results = P.poll_fleet()
    # Localhost fetch of hud-observer's match feed; {} when it is down, and
    # the document simply carries no match blocks that run.
    hud = P.fetch_hud()
    public, detail = P.public_document(results, hud=hud), P.detail_document(results)

    if args.dry_run:
        import json
        print(json.dumps(public, indent=2))
        return 0

    try:
        # public.json is served by nginx as a static file; detail.json is
        # operator-only and lives outside the web root.
        P.write_atomic(args.public, public, mode=0o644)
        P.write_atomic(args.detail, detail, mode=0o600)
    except OSError as exc:
        print(f"support-poller: write failed: {exc}", file=sys.stderr)
        return 1

    s = public["summary"]
    print(f"support-poller: {s['up']}/{s['total']} up, {s['players']} players")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
