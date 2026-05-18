#!/usr/bin/env python3
"""Poll the WSDoD LAN 2026 published-CSV for the user's announced team
renames. When any rename appears, re-run the builder and exit 0. After
12 attempts at 60s spacing (~12 min), exit 2 (timeout)."""
import urllib.request
import urllib.error
import subprocess
import sys
import io
import time
from pathlib import Path

# Force UTF-8 stdout on Windows (default cp1252 chokes on unicode).
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)
except Exception:
    pass

CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRn8bMqKwDK8HfdNFQuGglHY3fibds019dp22DAoJdJ49SqUUacu8huNBqS5em4F_H_o1ogFaKtLV93"
    "/pub?output=csv"
)
# Any of these in the published CSV means the user's edits propagated.
SENTINELS = ["FJTM", "Nien's Money Crew", "ck's gooners", "Money Crew", "gooners"]
MAX_ATTEMPTS = 12
INTERVAL_S = 60
HERE = Path(__file__).resolve().parent


def fetch() -> str:
    req = urllib.request.Request(
        CSV_URL,
        headers={"User-Agent": "WSDoD-Poll/1.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")


def main() -> int:
    last_size = -1
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            csv = fetch()
        except (urllib.error.URLError, OSError) as e:
            print(f"poll {attempt:02d}/{MAX_ATTEMPTS}: fetch error: {e}", flush=True)
            time.sleep(INTERVAL_S)
            continue

        size = len(csv)
        size_note = "" if size == last_size else f" (size changed: {last_size} -> {size})"
        last_size = size

        hit = next((s for s in SENTINELS if s in csv), None)
        if hit:
            print(
                f"poll {attempt:02d}/{MAX_ATTEMPTS}: CHANGE DETECTED — "
                f"sentinel {hit!r} present. Re-running builder.",
                flush=True,
            )
            result = subprocess.run(
                [sys.executable, "builder.py", "--verbose"],
                cwd=HERE,
                capture_output=True,
                text=True,
            )
            print(result.stdout, flush=True)
            print(result.stderr, flush=True)
            if result.returncode == 0:
                print("OK: poll → rebuild succeeded.", flush=True)
                return 0
            print(f"FAIL: builder exited {result.returncode}", flush=True)
            return 1

        print(
            f"poll {attempt:02d}/{MAX_ATTEMPTS}: no sentinel yet"
            f"{size_note}; sleeping {INTERVAL_S}s.",
            flush=True,
        )
        if attempt < MAX_ATTEMPTS:
            time.sleep(INTERVAL_S)

    print(
        f"TIMEOUT after {MAX_ATTEMPTS} attempts ({MAX_ATTEMPTS * INTERVAL_S}s). "
        "Cache still serving old content; recommend File → Share → Publish to web "
        "→ Republish content, or accept overrides path.",
        flush=True,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
