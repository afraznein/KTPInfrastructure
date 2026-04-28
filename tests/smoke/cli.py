"""Smoke-test CLI.

Usage:
    python -m tests.smoke.cli wait-ready --port 27016 [--rcon-password changeme]
    python -m tests.smoke.cli rcon "amx modules" --port 27016 ...
    python -m tests.smoke.cli assert-modules --port 27016 --expect amxxcurl,reapi,dodx
    python -m tests.smoke.cli assert-plugins --port 27016 --expect KTPMatchHandler.amxx,...
    python -m tests.smoke.cli assert-no-failed --port 27016

Exit codes:
    0  all assertions passed
    1  assertion failure (a module/plugin was missing or not running)
    2  infrastructure error (rcon timeout, bad password, network)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .asserts import (
    assert_modules_loaded,
    assert_no_failed_modules,
    assert_no_failed_plugins,
    assert_plugins_running,
)
from .rcon import RconAuthError, RconError
from .server_handle import ServerHandle

EXIT_OK = 0
EXIT_ASSERT = 1
EXIT_INFRA = 2


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _add_target_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--host", default="127.0.0.1", help="rcon target host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, required=True, help="rcon target UDP port")
    p.add_argument(
        "--rcon-password",
        default="changeme",
        help="rcon password (default: changeme — matches config/local/dodserver.cfg)",
    )


def _make_handle(args: argparse.Namespace) -> ServerHandle:
    return ServerHandle(host=args.host, port=args.port, rcon_password=args.rcon_password)


def cmd_wait_ready(args: argparse.Namespace) -> int:
    handle = _make_handle(args)
    handle.wait_ready(timeout=args.timeout, poll_interval=args.poll)
    print(f"server at {args.host}:{args.port} is rcon-responsive", flush=True)
    return EXIT_OK


def cmd_rcon(args: argparse.Namespace) -> int:
    handle = _make_handle(args)
    output = handle.rcon(args.command, timeout=args.timeout)
    print(output, end="" if output.endswith("\n") else "\n")
    return EXIT_OK


def cmd_assert_modules(args: argparse.Namespace) -> int:
    handle = _make_handle(args)
    expected = _split_csv(args.expect)
    rows = assert_modules_loaded(handle, expected, require_running=not args.allow_loaded_only)
    print(f"OK: all {len(expected)} expected modules running ({len(rows)} loaded total)")
    return EXIT_OK


def cmd_assert_plugins(args: argparse.Namespace) -> int:
    handle = _make_handle(args)
    expected = _split_csv(args.expect)
    rows = assert_plugins_running(handle, expected)
    print(f"OK: all {len(expected)} expected plugins running ({len(rows)} loaded total)")
    return EXIT_OK


def cmd_assert_no_failed(args: argparse.Namespace) -> int:
    handle = _make_handle(args)
    mod_rows = assert_no_failed_modules(handle)
    plug_rows = assert_no_failed_plugins(handle)
    print(f"OK: no failed modules ({len(mod_rows)}) or plugins ({len(plug_rows)})")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tests.smoke.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    wr = sub.add_parser("wait-ready", help="Block until rcon answers")
    _add_target_args(wr)
    wr.add_argument("--timeout", type=float, default=60.0, help="overall timeout in seconds")
    wr.add_argument("--poll", type=float, default=1.0, help="poll interval in seconds")
    wr.set_defaults(func=cmd_wait_ready)

    rc = sub.add_parser("rcon", help="Run an arbitrary rcon command and print output")
    _add_target_args(rc)
    rc.add_argument("command", help="command to send (quote multi-word commands)")
    rc.add_argument("--timeout", type=float, default=2.0)
    rc.set_defaults(func=cmd_rcon)

    am = sub.add_parser("assert-modules", help="Assert expected modules are loaded")
    _add_target_args(am)
    am.add_argument("--expect", required=True, help="comma-separated module names")
    am.add_argument(
        "--allow-loaded-only",
        action="store_true",
        help="accept status='loaded' as well as 'running'",
    )
    am.set_defaults(func=cmd_assert_modules)

    ap = sub.add_parser("assert-plugins", help="Assert expected plugins are running")
    _add_target_args(ap)
    ap.add_argument("--expect", required=True, help="comma-separated plugin names or .amxx files")
    ap.set_defaults(func=cmd_assert_plugins)

    nf = sub.add_parser("assert-no-failed", help="Assert no module/plugin is in failed state")
    _add_target_args(nf)
    nf.set_defaults(func=cmd_assert_no_failed)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return EXIT_ASSERT
    except RconAuthError as exc:
        print(f"INFRA: rcon auth rejected: {exc}", file=sys.stderr)
        return EXIT_INFRA
    except RconError as exc:
        print(f"INFRA: {exc}", file=sys.stderr)
        return EXIT_INFRA


if __name__ == "__main__":
    raise SystemExit(main())
