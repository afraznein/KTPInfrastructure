"""GoldSrc UDP rcon client.

Wire format (verified against KTPReHLDS rehlds/engine/sv_main.cpp):

  Challenge request   client -> server   \xff\xff\xff\xffchallenge rcon\n\0
  Challenge response  server -> client   \xff\xff\xff\xffchallenge rcon <num>\n\0
  Rcon request        client -> server   \xff\xff\xff\xffrcon <num> "<pass>" <cmd>\n\0
  Rcon response       server -> client   \xff\xff\xff\xffl<output>\0\0

Multi-packet responses: server sends one A2A_PRINT packet per redirect flush;
large outputs (e.g. `amx plugins`) span multiple packets. The client drains
until a short inactivity gap, then concatenates.

Split packets: when a single flush exceeds the routeable-packet limit
(~1400 bytes), NET_SendPacket fragments it with the GoldSrc SPLITPACKET
header instead of a plain A2A_PRINT:

  int32 -2 (\xfe\xff\xff\xff) | int32 sequence id | byte (num << 4 | total)

Fragments concatenate (in packet-number order) into one ordinary
\xff\xff\xff\xffl<output> packet. First seen live 2026-07-10: a
`changelevel` response crossed the boundary on the 2.7.21 stack and the
then-reassembly-less client raised "response missing 0xFFFFFFFF prefix".

Stdlib only. Designed to run anywhere Python runs — WSL, hosted Linux runners,
self-hosted runner, dev laptop.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass

PREFIX = b"\xff\xff\xff\xff"
SPLIT_PREFIX = b"\xfe\xff\xff\xff"
_SPLIT_HEADER_LEN = 9  # marker(4) + sequence id(4) + packet-number byte(1)
A2A_PRINT = ord("l")


class RconError(Exception):
    """Generic rcon failure (network, protocol, server response)."""


class RconAuthError(RconError):
    """Server rejected our password / challenge."""


@dataclass
class RconClient:
    host: str
    port: int
    password: str
    timeout: float = 2.0
    """Single-packet receive timeout. Total wall time for a command is bounded
    by `connect_timeout + timeout * (1 + max_response_packets)`."""
    connect_timeout: float = 5.0
    """Max wall time spent waiting for the initial challenge response."""
    drain_timeout: float = 0.4
    """Inactivity gap that signals end-of-response. Smaller = faster, but risks
    truncating very-large responses if the server is slow to flush."""

    def execute(self, command: str) -> str:
        """Send `command` and return the concatenated server response.

        Raises RconAuthError on bad password / bad challenge.
        Raises RconError on timeout / malformed response.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(self.connect_timeout)
            challenge = self._get_challenge(sock)
            sock.settimeout(self.timeout)
            payload = self._build_rcon_request(challenge, command)
            sock.sendto(payload, (self.host, self.port))
            output = self._drain_response(sock)
        finally:
            sock.close()

        if output.startswith("Bad rcon_password"):
            raise RconAuthError(output.strip())
        return output

    def _get_challenge(self, sock: socket.socket) -> str:
        sock.sendto(PREFIX + b"challenge rcon\n\0", (self.host, self.port))
        data, _ = sock.recvfrom(4096)
        if not data.startswith(PREFIX):
            raise RconError(f"challenge response missing 0xFFFFFFFF prefix: {data!r}")
        body = data[len(PREFIX):].rstrip(b"\x00\n").decode("utf-8", errors="replace")
        # body looks like: "challenge rcon 1234567890"
        parts = body.split()
        if len(parts) < 3 or parts[0] != "challenge" or parts[1] != "rcon":
            raise RconError(f"unexpected challenge response: {body!r}")
        return parts[2]

    def _build_rcon_request(self, challenge: str, command: str) -> bytes:
        # Quote the password so embedded spaces / special chars survive COM_Parse.
        # Quote any embedded double-quotes by closing+reopening (engine COM_Parse
        # has no escape syntax), but realistically passwords here are simple.
        quoted_pw = '"' + self.password.replace('"', '') + '"'
        line = f"rcon {challenge} {quoted_pw} {command}\n"
        return PREFIX + line.encode("utf-8") + b"\x00"

    def _drain_response(self, sock: socket.socket) -> str:
        chunks: list[str] = []
        reasm = _SplitReassembler()

        # First logical packet: required. A split fragment doesn't complete a
        # logical packet by itself, so keep receiving (each recv re-armed with
        # the full `timeout`) until reassembly yields one.
        while not chunks:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout as exc:
                if reasm.pending:
                    raise RconError(
                        f"split rcon response never completed: {reasm.describe()}"
                    ) from exc
                raise RconError("no rcon response within timeout") from exc
            text = reasm.ingest(data)
            if text is not None:
                chunks.append(text)

        # Subsequent packets: short drain window. Stop when no packet arrives
        # within drain_timeout — server has nothing left to send.
        sock.settimeout(self.drain_timeout)
        while True:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                break
            text = reasm.ingest(data)
            if text is not None:
                chunks.append(text)

        if reasm.pending:
            raise RconError(
                f"split rcon response incomplete at drain end: {reasm.describe()}"
            )
        return "".join(chunks)


class _SplitReassembler:
    """Reassembles GoldSrc SPLITPACKET fragments into logical packets.

    ingest() returns the unwrapped text when a datagram completes a logical
    packet (immediately, for ordinary unsplit packets), else None. Fragments
    may arrive out of order; sets are keyed by sequence id so interleaved
    split responses can't cross-contaminate.
    """

    def __init__(self) -> None:
        self._sets: dict[int, dict[int, bytes]] = {}
        self._totals: dict[int, int] = {}

    @property
    def pending(self) -> bool:
        return bool(self._sets)

    def describe(self) -> str:
        return ", ".join(
            f"seq={seq}: {len(parts)}/{self._totals[seq]} fragments"
            for seq, parts in self._sets.items()
        )

    def ingest(self, data: bytes) -> str | None:
        if not data.startswith(SPLIT_PREFIX):
            return _unwrap_print_packet(data)
        if len(data) <= _SPLIT_HEADER_LEN:
            raise RconError(f"split packet too short: {data!r}")
        seq = int.from_bytes(data[4:8], "little")
        num, total = data[8] >> 4, data[8] & 0x0F
        if total == 0 or num >= total:
            raise RconError(
                f"split packet bad counters (num={num} total={total}): {data[:16]!r}"
            )
        known_total = self._totals.setdefault(seq, total)
        if known_total != total:
            raise RconError(
                f"split packet total mismatch for seq={seq}: {known_total} vs {total}"
            )
        self._sets.setdefault(seq, {})[num] = data[_SPLIT_HEADER_LEN:]
        parts = self._sets[seq]
        if len(parts) < total:
            return None
        whole = b"".join(parts[n] for n in sorted(parts))
        del self._sets[seq]
        del self._totals[seq]
        return _unwrap_print_packet(whole)


def _unwrap_print_packet(packet: bytes) -> str:
    if not packet.startswith(PREFIX):
        raise RconError(f"response missing 0xFFFFFFFF prefix: {packet!r}")
    body = packet[len(PREFIX):]
    if not body or body[0] != A2A_PRINT:
        raise RconError(f"response missing A2A_PRINT 'l' byte: {packet!r}")
    # Strip the 'l' byte and any trailing null bytes.
    return body[1:].rstrip(b"\x00").decode("utf-8", errors="replace")


def wait_until_responsive(
    host: str,
    port: int,
    password: str,
    *,
    overall_timeout: float = 60.0,
    poll_interval: float = 1.0,
    probe_command: str = "version",
) -> RconClient:
    """Poll rcon until the server answers `probe_command` cleanly.

    Returns a configured RconClient on success. Raises RconError on overall
    timeout. Used as the boot-ready signal — booting a fresh hlds_linux takes
    5-15 seconds and there is no reliable stdout marker that survives across
    versions, so we just retry until we get a good response.
    """
    client = RconClient(host=host, port=port, password=password)
    deadline = time.monotonic() + overall_timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            output = client.execute(probe_command)
            if output:
                return client
        except RconAuthError:
            # Auth error means the server IS up — fail fast, retrying won't help.
            raise
        except (RconError, OSError) as exc:
            last_error = exc
        time.sleep(poll_interval)
    msg = f"server at {host}:{port} did not become rcon-responsive within {overall_timeout:.0f}s"
    if last_error is not None:
        msg += f" (last error: {last_error})"
    raise RconError(msg)
