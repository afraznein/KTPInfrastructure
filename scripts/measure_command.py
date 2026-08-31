#!/usr/bin/env python3
"""Run a local command and write machine-readable elapsed/CPU/peak-memory evidence."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - Windows host; Linux CI/container has it.
    resource = None


def usage_snapshot():
    if resource is None:
        return None
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own, children


def usage_delta(before, after):
    if before is None or after is None:
        return {"user_cpu_seconds": None, "system_cpu_seconds": None, "peak_rss_bytes": None}
    before_self, before_children = before
    after_self, after_children = after
    user = (
        after_self.ru_utime + after_children.ru_utime
        - before_self.ru_utime - before_children.ru_utime
    )
    system = (
        after_self.ru_stime + after_children.ru_stime
        - before_self.ru_stime - before_children.ru_stime
    )
    # Linux reports KiB; macOS reports bytes. ru_maxrss is a high-water mark,
    # so use the post-command value rather than pretending it is additive.
    peak = max(after_self.ru_maxrss, after_children.ru_maxrss)
    if sys.platform != "darwin":
        peak *= 1024
    return {
        "user_cpu_seconds": round(user, 6),
        "system_cpu_seconds": round(system, 6),
        "peak_rss_bytes": int(peak),
    }


def run(command: list[str]) -> tuple[int, dict]:
    if not command:
        raise ValueError("a command is required after --")
    before = usage_snapshot()
    started = time.perf_counter()
    completed = subprocess.run(command, check=False)
    elapsed = time.perf_counter() - started
    result = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": [Path(command[0]).name, *command[1:]],
        "exit_code": completed.returncode,
        "elapsed_seconds": round(elapsed, 6),
        "platform": platform.platform(),
        "pid": os.getpid(),
        **usage_delta(before, usage_snapshot()),
    }
    return completed.returncode, result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        exit_code, result = run(args.command)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"measure command: {exc}", file=sys.stderr)
        return 2
    print(
        f"measured: exit={exit_code} elapsed={result['elapsed_seconds']:.3f}s "
        f"peak_rss={result['peak_rss_bytes']}"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
