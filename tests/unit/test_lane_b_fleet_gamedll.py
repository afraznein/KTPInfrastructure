"""The Lane B image loads the fleet's game DLL, dlls/dod_i386.so, and pins its bytes.

The Dockerfile's install layer is executed for real under a shell against a temp game
tree, so these tests exercise the commands the build runs rather than a reading of
their text.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import zlib
from pathlib import Path

from tests.e2e_stats import metamod

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = ROOT / "build/lane-b"
DOCKERFILE = CONTEXT / "Dockerfile"
BINARY = CONTEXT / "gamedll/dod_i386.so"

# The identity the fleet runs and KTP-ReHLDS's door reversal guard checks for.
FLEET_MD5 = "4f4727b2390d3a0ed6f5ad862dd6d4be"

SH = shutil.which("dash") or os.environ.get("KTP_TEST_BASH", "bash")

_STOCK_LIBLIST = (
    'game "Day of Defeat"\n'
    'gamedll "dlls\\dod.dll"\n'
    'gamedll_linux "dlls/dod.so"\n'
    'gamedll_osx "dlls\\dod.dylib"\n'
)


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _arg(name: str) -> str:
    m = re.search(rf"^ARG {name}=(\S+)$", _dockerfile(), re.M)
    assert m, f"no ARG {name} in {DOCKERFILE}"
    return m.group(1)


def _copy_source() -> str:
    m = re.search(r"^COPY (\S+) /opt/hlds/dod/(\S+)$", _dockerfile(), re.M)
    assert m, "no COPY into the game tree"
    assert m.group(2) == metamod.FLEET_GAMEDLL
    return m.group(1)


def _gamedll_layer() -> str:
    """The RUN block after the COPY, joined the way Docker joins it (comment lines dropped)."""
    lines = _dockerfile().splitlines()
    copy = next(i for i, line in enumerate(lines) if line.startswith(f"COPY {_copy_source()} "))
    start = next(i for i in range(copy + 1, len(lines)) if lines[i].startswith("RUN "))
    block = []
    for line in lines[start:]:
        if line.lstrip().startswith("#"):
            continue
        block.append(line)
        if not line.rstrip().endswith("\\"):
            break
    return " ".join(line.rstrip().rstrip("\\") for line in block)[len("RUN "):]


def _run_layer(tmp_path: Path, *, dll: bytes, pin: bytes, liblist: str):
    dlls = tmp_path / "hlds/dod/dlls"
    dlls.mkdir(parents=True)
    (dlls / "dod_i386.so").write_bytes(dll)
    (tmp_path / "hlds/dod/liblist.gam").write_bytes(liblist.encode())
    command = _gamedll_layer().replace("/opt/hlds", (tmp_path / "hlds").as_posix())
    env = dict(os.environ, GAMEDLL_SHA256=hashlib.sha256(pin).hexdigest())
    return subprocess.run([SH, "-c", command], capture_output=True, text=True, env=env)


def _liblist(tmp_path: Path) -> str:
    return (tmp_path / "hlds/dod/liblist.gam").read_bytes().decode()


# --- the committed bytes ---------------------------------------------------------


def test_the_committed_binary_matches_the_build_pin():
    assert hashlib.sha256(BINARY.read_bytes()).hexdigest() == _arg("GAMEDLL_SHA256")


def test_the_committed_binary_is_the_fleet_build():
    data = BINARY.read_bytes()
    assert hashlib.md5(data).hexdigest() == FLEET_MD5
    assert f"{zlib.crc32(data):08X}" == metamod.FLEET_GAMEDLL_CRC32


def test_the_binary_is_in_the_build_context_and_not_the_vendor_cache():
    src = _copy_source()
    assert (CONTEXT / src).resolve() == BINARY.resolve()
    # vendor/ is gitignored and overwritten by the CI cache restore.
    assert not src.startswith("vendor/")


def test_the_layer_runs_before_metamod_snapshots_the_production_liblist():
    text = _dockerfile()
    snapshot = text.index("liblist.gam.production")
    assert text.index(f"COPY {_copy_source()} ") < snapshot
    assert text.index("gamedll_linux[[:space:]]+)") < snapshot


# --- the install layer, executed ---------------------------------------------------


def test_the_layer_points_liblist_at_the_fleet_dll_and_nothing_else(tmp_path):
    result = _run_layer(tmp_path, dll=b"dll", pin=b"dll", liblist=_STOCK_LIBLIST)
    assert result.returncode == 0, result.stderr
    expected = _STOCK_LIBLIST.replace('"dlls/dod.so"', f'"{metamod.FLEET_GAMEDLL}"')
    assert _liblist(tmp_path) == expected


def test_a_crlf_liblist_is_rewritten_too(tmp_path):
    # Line-ending preservation is sed's business and differs by platform; the target is ours.
    crlf = _STOCK_LIBLIST.replace("\n", "\r\n")
    result = _run_layer(tmp_path, dll=b"dll", pin=b"dll", liblist=crlf)
    assert result.returncode == 0, result.stderr
    found = re.findall(r'^gamedll_linux "([^"]*)"', _liblist(tmp_path), re.M)
    assert found == [metamod.FLEET_GAMEDLL]


def test_bytes_that_miss_the_pin_fail_the_build(tmp_path):
    result = _run_layer(tmp_path, dll=b"stock dod.so", pin=b"dll", liblist=_STOCK_LIBLIST)
    assert result.returncode != 0
    assert _liblist(tmp_path) == _STOCK_LIBLIST


def test_a_liblist_without_gamedll_linux_fails_the_build(tmp_path):
    no_line = "".join(line + "\n" for line in _STOCK_LIBLIST.splitlines()
                      if not line.startswith("gamedll_linux"))
    result = _run_layer(tmp_path, dll=b"dll", pin=b"dll", liblist=no_line)
    assert result.returncode != 0


def test_a_second_gamedll_linux_line_fails_the_build(tmp_path):
    doubled = _STOCK_LIBLIST + 'gamedll_linux "dlls/other.so"\n'
    result = _run_layer(tmp_path, dll=b"dll", pin=b"dll", liblist=doubled)
    assert result.returncode != 0


def test_metamod_loads_the_same_dll_the_image_names():
    topo_default = metamod.enable_metamod.__kwdefaults__["real_gamedll"]
    assert topo_default == metamod.FLEET_GAMEDLL
    assert f'"{metamod.FLEET_GAMEDLL}"' in _gamedll_layer()
