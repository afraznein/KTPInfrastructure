"""Direct subprocess boot — no docker.

Runs hlds_linux from a server tree, captures stdout, polls rcon until ready,
and tears down on context exit. Same `ServerHandle` API as `boot.py`.

On Linux: launches hlds_linux directly.
On Windows: launches via `wsl bash -c` so the same ELF binary runs under WSL.

Intended use cases:
- Local proof / dev iteration without docker
- CI on ubuntu-latest where artifacts are pre-built and we want a fast
  inner-loop boot (no container build)
- Self-hosted runner where docker would add overhead

For the docker compose path, see boot.py.
"""

from __future__ import annotations

import os
import platform
import shlex
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .server_handle import ServerHandle


def _free_udp_port(preferred: int | None = None) -> int:
    """Bind-then-close to find a free UDP port. Race window is tiny but real;
    callers should retry once on bind failure if they care."""
    if preferred is not None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
        finally:
            s.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wsl_path(win_path: Path) -> str:
    """Convert a Windows path to a WSL path: N:\\foo\\bar -> /mnt/n/foo/bar."""
    parts = win_path.resolve().parts
    drive = parts[0].rstrip(":\\").lower()
    rest = "/".join(parts[1:])
    return f"/mnt/{drive}/{rest}"


def _build_hlds_argv(
    serverfiles: Path,
    *,
    map_name: str,
    port: int,
    maxplayers: int,
    rcon_password: str,
    server_cfg: str,
    extra_args: list[str],
) -> list[str]:
    """Build the hlds_linux command line common to both Linux and WSL paths."""
    return [
        "./hlds_linux",
        "-game", "dod",
        "-strictportbind",
        "+ip", "127.0.0.1",
        "-port", str(port),
        "+clientport", str(port - 10),
        "+map", map_name,
        "+maxplayers", str(maxplayers),
        "-pingboost", "2",
        "+rcon_password", rcon_password,
        "+sv_lan", "1",
        "+servercfgfile", server_cfg,
        *extra_args,
    ]


def _ld_library_path(serverfiles: Path, *, wsl_form: bool = False) -> str:
    """Build LD_LIBRARY_PATH so hlds_linux's dlopen("steamclient.so") resolves.

    The engine (after KTP-ReHLDS 3.22.x) calls dlopen with a bare name; the
    dynamic linker won't search CWD, so without LD_LIBRARY_PATH it fails with
    `cannot open shared object file: No such file or directory` even when a
    copy exists in the serverfiles tree. ~/.steam/sdk32 is the production
    fallback path (populated by steamcmd). serverfiles/ first matches the
    same precedence the engine uses internally.
    """
    if wsl_form:
        sf_dir = _wsl_path(serverfiles)
        sdk32 = "$HOME/.steam/sdk32"
    else:
        sf_dir = str(serverfiles)
        sdk32 = str(Path.home() / ".steam" / "sdk32")
    return f"{sf_dir}:{sdk32}"


def _spawn(
    serverfiles: Path,
    argv: list[str],
    log_file: Path,
) -> subprocess.Popen:
    """Spawn hlds_linux. On Windows this trampolines through WSL so the same
    ELF binary executes under a real Linux kernel."""
    log_handle = log_file.open("wb")
    if platform.system() == "Windows":
        wsl_dir = _wsl_path(serverfiles)
        cmdline = " ".join(shlex.quote(a) for a in argv)
        ld_path = _ld_library_path(serverfiles, wsl_form=True)
        wsl_argv = [
            "wsl", "bash", "-c",
            f"cd {shlex.quote(wsl_dir)} && export LD_LIBRARY_PATH={shlex.quote(ld_path)}:${{LD_LIBRARY_PATH:-}} && exec {cmdline}",
        ]
        return subprocess.Popen(
            wsl_argv,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    # Linux / macOS-WSL: exec directly from the serverfiles dir.
    env = dict(os.environ)
    ld_path = _ld_library_path(serverfiles, wsl_form=False)
    existing = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = f"{ld_path}:{existing}" if existing else ld_path
    return subprocess.Popen(
        argv,
        cwd=str(serverfiles),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        preexec_fn=os.setsid if hasattr(os, "setsid") else None,
    )


def _terminate(proc: subprocess.Popen, timeout: float = 10.0) -> None:
    """Send SIGTERM, then SIGKILL after `timeout`. WSL-trampolined processes
    on Windows need the trampoline killed too, hence Popen.terminate."""
    if proc.poll() is not None:
        return
    try:
        if platform.system() != "Windows" and hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, OSError):
        return
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if platform.system() != "Windows" and hasattr(os, "killpg"):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, OSError):
            pass
        proc.wait(timeout=5.0)


@contextmanager
def booted_subprocess(
    serverfiles: Path,
    *,
    map_name: str = "dod_anzio",
    port: int | None = None,
    maxplayers: int = 13,
    rcon_password: str = "smoketest",
    server_cfg: str = "test_server.cfg",
    log_file: Path | None = None,
    boot_timeout: float = 90.0,
    extra_args: list[str] | None = None,
) -> Iterator[ServerHandle]:
    """Boot hlds_linux from `serverfiles`, yield a ServerHandle, tear down.

    `serverfiles` must contain hlds_linux + the dod/ tree. `server_cfg` is
    relative to dod/ (the engine looks there for cfg files).

    On exit, the last 100 lines of stdout are printed if the body raised, so
    failures show server-side context inline.
    """
    serverfiles = Path(serverfiles).resolve()
    chosen_port = _free_udp_port(preferred=port)
    log_file = log_file or (serverfiles / f"smoke-{chosen_port}.log")
    argv = _build_hlds_argv(
        serverfiles,
        map_name=map_name,
        port=chosen_port,
        maxplayers=maxplayers,
        rcon_password=rcon_password,
        server_cfg=server_cfg,
        extra_args=extra_args or [],
    )
    proc = _spawn(serverfiles, argv, log_file)
    handle = ServerHandle(host="127.0.0.1", port=chosen_port, rcon_password=rcon_password)
    try:
        # Don't wait full boot_timeout if the process died early.
        deadline = time.monotonic() + boot_timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"hlds_linux exited before becoming ready (rc={proc.returncode}); "
                    f"see {log_file}"
                )
            try:
                handle.wait_ready(timeout=2.0, poll_interval=0.5)
                break
            except Exception:
                continue
        else:
            raise TimeoutError(
                f"hlds_linux did not respond to rcon within {boot_timeout:.0f}s; "
                f"see {log_file}"
            )
        yield handle
    except BaseException:
        try:
            tail = _tail_lines(log_file, 100)
            print(f"--- {log_file.name} (tail 100) ---", file=sys.stderr)
            print(tail, file=sys.stderr)
        except Exception:
            pass
        raise
    finally:
        _terminate(proc)


def _tail_lines(path: Path, n: int) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 4096
            data = b""
            while size > 0 and data.count(b"\n") <= n:
                read = min(block, size)
                size -= read
                f.seek(size)
                data = f.read(read) + data
            lines = data.splitlines()[-n:]
            return b"\n".join(lines).decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""
