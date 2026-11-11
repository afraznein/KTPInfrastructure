"""The tier-2 job's first step refuses a root runner.

Pull-request code runs on that runner, so a root service would hand it the whole
data server. The step's own text is pulled out of the workflow and run under
bash with `id` stubbed, so the test exercises what GitHub runs, not a copy.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "tier2-integration.yml"
STEP = "Refuse to run as root"

BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def _steps() -> list[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    job = text.split("\n  integration:\n", 1)[1]
    body = job.split("\n    steps:\n", 1)[1]
    return re.findall(r"^      - name: (.+)$", body, re.MULTILINE)


def _script() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    m = re.search(
        rf"^      - name: {re.escape(STEP)}\n(?:        #.*\n)*        run: \|\n((?:          .*\n|\n)+)",
        text,
        re.MULTILINE,
    )
    assert m, "step not found"
    return "\n".join(line[10:] for line in m.group(1).splitlines()) + "\n"


def _run(tmp_path: Path, uid: str) -> subprocess.CompletedProcess[str]:
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "id").write_text(
        '#!/usr/bin/env bash\ncase "$1" in -u) echo ' + uid + ' ;; -un) echo zqwbw1110user ;; esac\n',
        encoding="utf-8",
        newline="\n",
    )
    (stub / "id").chmod(0o755)
    env = dict(os.environ, PATH=f"{stub}{os.pathsep}{os.environ['PATH']}")
    return subprocess.run([BASH, "-e", "-c", _script()], env=env, capture_output=True, text=True)


def test_it_is_the_first_step() -> None:
    assert _steps()[0] == STEP


def test_root_is_refused(tmp_path: Path) -> None:
    r = _run(tmp_path, "0")
    assert r.returncode == 1
    assert "::error::Tier 2 must not run as root" in r.stdout


def test_an_unprivileged_user_passes(tmp_path: Path) -> None:
    r = _run(tmp_path, "998")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "zqwbw1110user, uid 998" in r.stdout
