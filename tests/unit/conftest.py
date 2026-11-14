"""Shared setup for tests/unit.

Most shell-script tests here run `os.environ.get("KTP_TEST_BASH", "bash")`. On a
Windows workstation a bare `bash` is WSL's (System32\\bash.exe), which cannot open
the `C:/...` probe paths, so every case dies with exit 127 and reads as a script
regression. When nothing is set, point KTP_TEST_BASH at a Git Bash that can see
this file. CI (Linux) is untouched.
"""
import os
import pathlib
import shutil
import subprocess
import sys


def _git_bash():
    git = shutil.which("git")
    if not git:
        return None
    root = pathlib.Path(git).resolve().parents[1]
    here = pathlib.Path(__file__).resolve().as_posix()
    for cand in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
        if not cand.is_file():
            continue
        probe = subprocess.run([str(cand), "-c", 'test -f "$1"', "_", here], capture_output=True)
        if probe.returncode == 0:
            return str(cand)
    return None


if sys.platform == "win32" and not os.environ.get("KTP_TEST_BASH"):
    found = _git_bash()
    if found:
        os.environ["KTP_TEST_BASH"] = found
