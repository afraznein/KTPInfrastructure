#!/usr/bin/env python3
"""Poll the fleet once and write the status documents. Run by a systemd timer.

One-shot rather than a daemon: a crashed daemon leaves a stale JSON that reads
as a healthy fleet, whereas a timer that stops firing leaves the same stale JSON
but is visible in `systemctl list-timers`. The page treats an old `generated`
stamp as unknown either way -- see STALE_AFTER in the status route.

Exit codes: 0 wrote both documents, 1 could not write, 8 wrote them but could
not push to the site. A fleet that is entirely down is still a successful poll
-- that is a real result, not an error.

8 is separate from 1 on purpose: the documents on disk are fine and the next
run will overwrite them, but ktpleague.gg is serving an increasingly stale
fleet and only this exit code says so. It is 8 rather than 2 because systemd
maps low exit codes to LSB names -- 2 renders as ``status=2/INVALIDARGUMENT``
and sends a reader hunting a bad CLI flag, while codes >= 8 display as bare
numbers. 2 is also what argparse itself exits with on a usage error, so the
two failures were indistinguishable in ``systemctl status``.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import poller as P  # noqa: E402

PUBLIC_DEFAULT = "/var/www/support.ktpdod.com/status/public.json"
DETAIL_DEFAULT = "/var/lib/support-web/detail.json"
PUSH_URL_DEFAULT = "https://ktpleague.gg/api/internal/servers/status"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--public", default=os.getenv("SUPPORT_PUBLIC_JSON", PUBLIC_DEFAULT),
                    help="served to anyone; allowlisted fields only")
    ap.add_argument("--detail", default=os.getenv("SUPPORT_DETAIL_JSON", DETAIL_DEFAULT),
                    help="operator view; MUST live outside the web root")
    ap.add_argument("--push-url", default=os.getenv("SUPPORT_PUSH_URL", PUSH_URL_DEFAULT),
                    help="ktpleague.gg ingest route; the page reads what lands there")
    ap.add_argument("--no-push", action="store_true", help="write the files only")
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

    # No secret means the push is not configured yet -- silent, because that is
    # the expected state until the site side ships, and a warning every 60s
    # trains everyone to ignore this unit's output.
    secret = os.getenv("SUPPORT_PUSH_SECRET", "")
    if args.no_push or not secret or not args.push_url:
        return 0

    ok, detail = P.push_public(public, args.push_url, secret)
    if not ok:
        print(f"support-poller: push failed: {detail}", file=sys.stderr)
        return 8
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
