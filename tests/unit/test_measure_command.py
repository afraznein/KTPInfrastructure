from __future__ import annotations

import json
import sys

from scripts import measure_command


def test_measure_command_preserves_exit_and_writes_evidence(tmp_path):
    output = tmp_path / "measurement.json"
    exit_code = measure_command.main([
        "--output", str(output), "--", sys.executable, "-c",
        "raise SystemExit(3)",
    ])
    result = json.loads(output.read_text())
    assert exit_code == 3
    assert result["exit_code"] == 3
    assert result["elapsed_seconds"] >= 0
    assert result["command"][0] in ("python", "python.exe", "python3")


def test_measure_command_requires_an_executable(tmp_path):
    assert measure_command.main(["--output", str(tmp_path / "missing.json")]) == 2
