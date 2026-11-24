"""Every script under scripts/ compiles without a SyntaxWarning.

An invalid escape in a docstring prints a SyntaxWarning at the top of every run,
so it lands in each weekly fleet-audit log and issue, where it reads like a fault
in the run. Python has said these become SyntaxErrors in a later release, at which
point the script stops starting at all.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
PY_FILES = sorted(SCRIPTS.rglob("*.py"))


def _compile_warnings(source: bytes, name: str) -> list[str]:
    # Before 3.12 an invalid escape is a DeprecationWarning, so match the message too.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        compile(source, name, "exec")
    return [f"line {w.lineno}: {w.message}" for w in caught
            if issubclass(w.category, SyntaxWarning)
            or "invalid escape sequence" in str(w.message)]


def test_the_scan_has_something_to_scan():
    assert len(PY_FILES) > 50


def test_the_scan_catches_an_invalid_escape():
    assert _compile_warnings(b'"""date +\\%Y"""\n', "probe")


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: p.relative_to(SCRIPTS).as_posix())
def test_compiles_without_syntax_warning(path: Path):
    found = _compile_warnings(path.read_bytes(), str(path))
    assert not found, found
