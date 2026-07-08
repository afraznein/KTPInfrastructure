"""docker compose driver for local smoke testing.

The existing `docker-compose.local.yml` already knows how to boot a full KTP
game server. This module is a thin Python wrapper that brings a single service
up, waits for rcon to answer, and tears it back down.

For CI on hosted GitHub runners with the same compose file we get identical
behaviour — the runner just needs docker installed (provided on ubuntu-latest).
For self-hosted runners with the artifacts pre-built, this is a near-instant
boot.

Direct subprocess boot lives in the sibling `boot_subprocess.py` (built for
the Docker-free Tier 2 runner on the data server) and returns the same
ServerHandle contract. This module remains the containerised path.
"""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .server_handle import ServerHandle

# Conventional port mapping defined in docker-compose.local.yml. Centralised
# here so the smoke harness has one place to look up "what host port did
# `ktp-game-1` get?". Keep in sync with docker-compose.local.yml.
SERVICE_PORT_MAP: dict[str, int] = {
    "ktp-game-1": 27016,
    "ktp-game-2": 27017,
}

DEFAULT_RCON_PASSWORD = "changeme"
DEFAULT_COMPOSE_FILE = (
    Path(__file__).resolve().parents[2] / "docker-compose.local.yml"
)


def _compose(
    *args: str,
    compose_file: Path = DEFAULT_COMPOSE_FILE,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose", "-f", str(compose_file), *args]
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=capture,
    )


def compose_up(
    service: str,
    *,
    compose_file: Path = DEFAULT_COMPOSE_FILE,
    rcon_password: str = DEFAULT_RCON_PASSWORD,
    boot_timeout: float = 90.0,
) -> ServerHandle:
    """Bring `service` up and return a handle once it answers rcon.

    Caller owns teardown — pair with compose_down(service) or use
    `with booted(service)` to guarantee cleanup.
    """
    if service not in SERVICE_PORT_MAP:
        known = ", ".join(sorted(SERVICE_PORT_MAP))
        raise ValueError(f"unknown compose service '{service}'; known: {known}")
    _compose("up", "-d", service, compose_file=compose_file)
    handle = ServerHandle(
        host="127.0.0.1",
        port=SERVICE_PORT_MAP[service],
        rcon_password=rcon_password,
    )
    handle.wait_ready(timeout=boot_timeout)
    return handle


def compose_down(
    service: str,
    *,
    compose_file: Path = DEFAULT_COMPOSE_FILE,
) -> None:
    """Stop + remove the container. Volumes preserved."""
    _compose("rm", "-sf", service, compose_file=compose_file)


def compose_logs(
    service: str,
    *,
    compose_file: Path = DEFAULT_COMPOSE_FILE,
    tail: int = 200,
) -> str:
    """Fetch the last `tail` lines of stdout. Useful for diagnosing red runs."""
    result = _compose(
        "logs", "--tail", str(tail), "--no-color", service,
        compose_file=compose_file,
        capture=True,
    )
    return result.stdout


@contextmanager
def booted(
    service: str,
    *,
    compose_file: Path = DEFAULT_COMPOSE_FILE,
    rcon_password: str = DEFAULT_RCON_PASSWORD,
    boot_timeout: float = 90.0,
) -> Iterator[ServerHandle]:
    """Context manager: bring `service` up, yield handle, tear down on exit.

    Logs are fetched and printed if the body raises, so test failures show
    server-side context without a manual `docker compose logs` step.
    """
    handle = compose_up(
        service,
        compose_file=compose_file,
        rcon_password=rcon_password,
        boot_timeout=boot_timeout,
    )
    try:
        yield handle
    except BaseException:
        try:
            print(f"--- {service} compose logs (tail 200) ---")
            print(compose_logs(service, compose_file=compose_file))
        except Exception:
            pass
        raise
    finally:
        compose_down(service, compose_file=compose_file)
