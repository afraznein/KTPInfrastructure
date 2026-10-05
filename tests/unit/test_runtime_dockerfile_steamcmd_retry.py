"""The HLDS install layer retries a transient steamcmd failure, and only so often.

The RUN block is executed for real under /bin/sh with a fake steamcmd that
fails a chosen number of times, so the test exercises the shell the image
build runs rather than a reading of the Dockerfile text.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "runtime/Dockerfile"
STEAMCMD = "/usr/games/steamcmd"
SH = shutil.which("sh") if os.name != "nt" else None

pytestmark = pytest.mark.skipif(SH is None, reason="needs a POSIX /bin/sh")


def _install_layer() -> str:
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.startswith("RUN ") and any(STEAMCMD in l for l in lines[i:i + 3]))
    block = []
    for line in lines[start:]:
        block.append(line)
        if not line.rstrip().endswith("\\"):
            break
    # Docker joins continuation lines before handing the command to /bin/sh -c.
    return " ".join(line.rstrip().rstrip("\\") for line in block)[len("RUN "):]


def _run(tmp_path: Path, fails: int) -> tuple[int, int]:
    counter = tmp_path / "calls"
    fake = tmp_path / "steamcmd"
    fake.write_text(
        "#!/bin/sh\n"
        f'n=$(cat "{counter}" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "{counter}"\n'
        f'[ "$n" -le {fails} ] && exit 8\n'
        "exit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    command = (_install_layer()
               .replace(STEAMCMD, str(fake))
               .replace("mkdir -p /opt/hlds", "true")
               .replace("sleep 30", "sleep 0"))
    result = subprocess.run([SH, "-c", command], capture_output=True, text=True)
    return result.returncode, int(counter.read_text())


def test_the_layer_really_invokes_steamcmd():
    # Control: the extraction found the install layer, not some other RUN.
    assert STEAMCMD in _install_layer()
    assert "+app_update 90 validate" in _install_layer()


def test_a_clean_install_runs_steamcmd_once(tmp_path):
    assert _run(tmp_path, fails=0) == (0, 1)


def test_a_transient_failure_is_retried_to_success(tmp_path):
    assert _run(tmp_path, fails=2) == (0, 3)


def test_retries_are_bounded_and_the_failure_code_survives(tmp_path):
    assert _run(tmp_path, fails=5) == (8, 3)
