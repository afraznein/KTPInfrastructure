"""The Lane B image bakes in the door scenario's map, pinned, and CI caches it.

The Dockerfile's install layer and the workflow's two vendor steps are executed
for real under a shell, with a fake curl, so these tests exercise the commands
the build runs rather than a reading of their text.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tests.e2e_stats import door_hold_scenario

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "build/lane-b/Dockerfile"
WORKFLOW = ROOT / ".github/workflows/lane-b-stats-e2e.yml"

# Docker runs RUN under /bin/sh, which is dash on the Ubuntu base; prefer it so a
# bash-only construct fails here rather than in the image build.
SH = shutil.which("dash") or os.environ.get("KTP_TEST_BASH", "bash")
BASH = os.environ.get("KTP_TEST_BASH", "bash")

ARG_RE = re.compile(r"^ARG ([A-Z0-9_]+)=(.*)$")
PINNED_RE = re.compile(r'^\s+install_pinned (\S+) "\$([A-Z0-9_]+)"')


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _args(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for line in text.splitlines()
            if (m := ARG_RE.match(line))}


def _pinned(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for line in text.splitlines()
            if (m := PINNED_RE.match(line))]


def _install_layer() -> str:
    lines = _dockerfile().splitlines()
    starts = [i for i, line in enumerate(lines)
              if line.startswith("RUN ") and any("install_pinned()" in l for l in lines[i:i + 3])]
    assert len(starts) == 1, f"expected one install_pinned layer, found {len(starts)}"
    block = []
    for line in lines[starts[0]:]:
        block.append(line)
        if not line.rstrip().endswith("\\"):
            break
    return " ".join(line.rstrip().rstrip("\\") for line in block)[len("RUN "):]


def _step_run(name: str) -> str:
    """The `run: |` body of one workflow step, dedented."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == f"- name: {name}"]
    assert len(starts) == 1, f"expected one step named {name!r}, found {len(starts)}"
    i = starts[0] + 1
    while lines[i].strip() != "run: |":
        assert not lines[i].lstrip().startswith("- name:"), f"step {name!r} has no run block"
        i += 1
    indent = len(lines[i]) - len(lines[i].lstrip()) + 2
    body = []
    for line in lines[i + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return "\n".join(body) + "\n"


def _fake_curl(tmp_path: Path, payloads: dict[str, bytes]) -> Path:
    """A curl that serves `payloads` by URL suffix and logs every URL it was asked for."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    store = tmp_path / "served"
    store.mkdir()
    cases = []
    for n, (suffix, data) in enumerate(payloads.items()):
        (store / str(n)).write_bytes(data)
        cases.append(f'  *{suffix}) cp "{store.as_posix()}/{n}" "$out" ;;')
    script = "\n".join([
        "#!/bin/sh",
        'out=""; url=""',
        'while [ $# -gt 0 ]; do',
        '  case "$1" in -o) out=$2; shift 2 ;; http*) url=$1; shift ;; *) shift ;; esac',
        "done",
        f'echo "$url" >> "{(tmp_path / "curl.log").as_posix()}"',
        'case "$url" in',
        *cases,
        "  *) exit 22 ;;",
        "esac",
        "",
    ])
    curl = bin_dir / "curl"
    curl.write_text(script, newline="\n")
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _curl_log(tmp_path: Path) -> list[str]:
    log = tmp_path / "curl.log"
    return log.read_text().split() if log.exists() else []


def _env(args: dict[str, str]) -> dict[str, str]:
    return dict(os.environ, **args)


def _with_fake_bin(bin_dir: Path, command: str) -> str:
    # A function, not PATH: Git Bash rebuilds PATH at startup and reads `C:` as a separator.
    return f'curl() {{ "{(bin_dir / "curl").as_posix()}" "$@"; }}\n' + command


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- what is baked ------------------------------------------------------------


def test_the_image_installs_the_map_the_door_scenario_loads():
    paths = [rel for rel, _ in _pinned(_dockerfile())]
    assert f"maps/{door_hold_scenario.MAP}.bsp" in paths
    # The scenario looks under <serverfiles>/dod/maps and the harness default is the image's /opt/hlds.
    assert 'dest="/opt/hlds/dod/$rel"' in _install_layer()


def test_every_installed_file_is_fetched_from_fastdl_and_pinned_to_a_sha256():
    text = _dockerfile()
    args = _args(text)
    assert args["FASTDL_URL"] == "https://fastdl.ktpdod.com/dod"
    pinned = _pinned(text)
    assert len(pinned) >= 1
    for rel, var in pinned:
        assert re.fullmatch(r"[0-9a-f]{64}", args.get(var, "")), f"{rel}: {var} is not a sha256 ARG"


def test_the_install_layer_comes_before_the_last_vendor_consumer_clears_it():
    text = _dockerfile()
    assert text.index("install_pinned()") < text.index("rm -rf /tmp/vendor")


# --- the install layer, executed ------------------------------------------------


def _run_layer(tmp_path: Path, *, served: dict[str, bytes], vendored: dict[str, bytes],
               preexisting: dict[str, bytes] | None = None,
               pins: dict[str, bytes] | None = None) -> subprocess.CompletedProcess:
    """Run the RUN block against a temp game tree. `pins` defaults to the served bytes."""
    pinned = _pinned(_dockerfile())
    root = tmp_path / "hlds"
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    for name, data in vendored.items():
        (vendor / name).write_bytes(data)
    for rel, data in (preexisting or {}).items():
        dest = root / "dod" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    pins = pins or served
    args = {"FASTDL_URL": "https://fastdl.example/dod"}
    args.update({var: _sha(pins[rel]) for rel, var in pinned})
    bin_dir = _fake_curl(tmp_path, {f"/dod/{rel}": data for rel, data in served.items()})
    command = (_install_layer()
               .replace("/opt/hlds", root.as_posix())
               .replace("/tmp/vendor", vendor.as_posix()))
    return subprocess.run([SH, "-c", _with_fake_bin(bin_dir, command)], capture_output=True,
                          text=True, env=_env(args))


def _payloads() -> dict[str, bytes]:
    return {rel: f"bytes of {rel}".encode() for rel, _ in _pinned(_dockerfile())}


def _installed(tmp_path: Path, rel: str) -> bytes:
    return (tmp_path / "hlds" / "dod" / rel).read_bytes()


def test_a_cold_build_fetches_every_file_from_fastdl(tmp_path):
    files = _payloads()
    result = _run_layer(tmp_path, served=files, vendored={})
    assert result.returncode == 0, result.stderr
    assert sorted(_curl_log(tmp_path)) == sorted(f"https://fastdl.example/dod/{rel}" for rel in files)
    for rel, data in files.items():
        assert _installed(tmp_path, rel) == data


def test_a_vendored_copy_is_used_and_nothing_is_fetched(tmp_path):
    files = _payloads()
    result = _run_layer(tmp_path, served={},
                        vendored={Path(rel).name: data for rel, data in files.items()},
                        pins=files)
    assert result.returncode == 0, result.stderr
    assert _curl_log(tmp_path) == []
    for rel, data in files.items():
        assert _installed(tmp_path, rel) == data


def test_fetched_bytes_that_miss_the_pin_fail_the_build(tmp_path):
    files = _payloads()
    wrong = {rel: data + b"!" for rel, data in files.items()}
    result = _run_layer(tmp_path, served=wrong, vendored={}, pins=files)
    assert result.returncode != 0


def test_a_vendored_copy_that_misses_the_pin_fails_the_build(tmp_path):
    files = _payloads()
    result = _run_layer(tmp_path, served=files,
                        vendored={Path(rel).name: data + b"!" for rel, data in files.items()},
                        pins=files)
    assert result.returncode != 0
    assert _curl_log(tmp_path) == []


def test_a_file_the_base_already_has_is_kept_when_it_matches(tmp_path):
    files = _payloads()
    rel = next(iter(files))
    result = _run_layer(tmp_path, served=files, vendored={}, preexisting={rel: files[rel]})
    assert result.returncode == 0, result.stderr
    assert f"https://fastdl.example/dod/{rel}" not in _curl_log(tmp_path)


def test_a_file_the_base_already_has_is_never_overwritten_when_it_differs(tmp_path):
    files = _payloads()
    rel = next(iter(files))
    result = _run_layer(tmp_path, served=files, vendored={}, preexisting={rel: b"stock bytes"})
    assert result.returncode != 0
    assert _installed(tmp_path, rel) == b"stock bytes"


# --- the workflow's cache, executed ---------------------------------------------


def _resolve(tmp_path: Path, dockerfile: str) -> tuple[subprocess.CompletedProcess, dict[str, str]]:
    work = tmp_path / "work"
    (work / "build/lane-b").mkdir(parents=True)
    (work / "build/lane-b/Dockerfile").write_text(dockerfile, encoding="utf-8", newline="\n")
    out = tmp_path / "github_output"
    out.write_text("")
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir()
    env = dict(os.environ, GITHUB_OUTPUT=out.as_posix(), RUNNER_TEMP=runner_temp.as_posix())
    result = subprocess.run([BASH, "-c", _step_run("Resolve the pinned vendor checksums")],
                            capture_output=True, text=True, cwd=work, env=env)
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return result, outputs


def _pinned_rows(outputs: dict[str, str]) -> list[tuple[str, str]]:
    rows = Path(outputs["pinned"]).read_text().splitlines()
    return [tuple(row.split(" ")) for row in rows]


def test_the_workflow_reads_every_pinned_file_out_of_the_dockerfile(tmp_path):
    text = _dockerfile()
    result, outputs = _resolve(tmp_path, text)
    assert result.returncode == 0, result.stdout + result.stderr
    args = _args(text)
    assert _pinned_rows(outputs) == [(rel, args[var]) for rel, var in _pinned(text)]
    assert outputs["fastdl_url"] == args["FASTDL_URL"]
    assert outputs["key"].startswith(f"lane-b-vendor-{args['NEW_BOT_SHA256']}-{args['METAMOD_SHA256']}-")


def test_bumping_a_map_pin_is_a_cache_miss_by_construction(tmp_path):
    text = _dockerfile()
    var = _pinned(text)[0][1]
    old = _args(text)[var]
    bumped = text.replace(f"ARG {var}={old}", f"ARG {var}={'0' * 64}")
    assert bumped != text
    _, before = _resolve(tmp_path / "a", text)
    _, after = _resolve(tmp_path / "b", bumped)
    assert before["key"] != after["key"]


def test_a_pin_that_will_not_parse_refuses_to_build_a_key(tmp_path):
    text = _dockerfile()
    var = _pinned(text)[0][1]
    broken = re.sub(rf"^ARG {var}=.*$", f"ARG {var}=not-a-sha", text, flags=re.M)
    result, outputs = _resolve(tmp_path, broken)
    assert result.returncode != 0
    assert "key" not in outputs
    assert var in result.stdout


def test_losing_every_install_pinned_line_is_an_error_not_an_empty_cache(tmp_path):
    stripped = "\n".join(line for line in _dockerfile().splitlines()
                         if not PINNED_RE.match(line)) + "\n"
    result, outputs = _resolve(tmp_path, stripped)
    assert result.returncode != 0
    assert "key" not in outputs


def test_the_supply_step_vendors_fastdl_files_under_the_name_the_dockerfile_reads(tmp_path):
    text = _dockerfile()
    _, outputs = _resolve(tmp_path / "resolve", text)
    rows = _pinned_rows(outputs)
    work = tmp_path / "work"
    vendor = work / "build/lane-b/vendor"
    vendor.mkdir(parents=True)
    bot, mm = b"bot", b"mm"
    (vendor / "new_bot.zip").write_bytes(bot)
    (vendor / "metamod.zip").write_bytes(mm)
    served = {rel: f"bytes of {rel}".encode() for rel, _ in rows}
    pinned = tmp_path / "pinned.txt"
    pinned.write_text("".join(f"{rel} {_sha(data)}\n" for rel, data in served.items()), newline="\n")
    bin_dir = _fake_curl(tmp_path, {f"/dod/{rel}": data for rel, data in served.items()})
    env = _env({
        "BOT_URL": "https://bot.example/x", "BOT_SHA": _sha(bot),
        "MM_URL": "https://mm.example/x", "MM_SHA": _sha(mm),
        "FASTDL_URL": "https://fastdl.example/dod", "PINNED": pinned.as_posix(),
    })
    command = _with_fake_bin(bin_dir, _step_run("Fetch and verify whatever the cache did not supply"))
    result = subprocess.run([BASH, "-c", command], capture_output=True, text=True, cwd=work, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    for rel, data in served.items():
        assert (vendor / Path(rel).name).read_bytes() == data
    assert sorted(_curl_log(tmp_path)) == sorted(f"https://fastdl.example/dod/{rel}" for rel in served)
