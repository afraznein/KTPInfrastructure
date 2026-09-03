"""Minimal A2S_INFO client for the GoldSrc fleet.

Only what the status page needs: hostname, map, players, max. No dependency --
the query is one UDP packet and the reply is a flat struct, so a library would
be more surface than code.

Timeout is deliberately generous. A 1.5s timeout produced a false TIMEOUT on a
healthy Atlanta instance during a 24/24 sweep that passed at 2.0s; a status page
that cries wolf is worse than none, so slow is not down.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass

QUERY = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"
PLAYER_QUERY = b"\xFF\xFF\xFF\xFFU\xFF\xFF\xFF\xFF"
DEFAULT_TIMEOUT = 2.5

# Every instance carries an HLTV proxy and it occupies a player slot. A2S counts
# it as a player and reports bots=0, so a naive count reads "24 players online"
# on a completely empty fleet -- measured against production 2026-08-05.
HLTV_MARKER = "HLTV"


class A2SError(Exception):
    pass


@dataclass(frozen=True)
class ServerInfo:
    hostname: str
    map: str
    players: int
    max_players: int
    bots: int

    @property
    def humans(self) -> int:
        """Slot count minus bots. Still includes HLTV -- use `count_humans`."""
        return max(0, self.players - self.bots)


class _Reader:
    def __init__(self, data: bytes):
        self.d, self.i = data, 0

    def byte(self) -> int:
        if self.i >= len(self.d):
            raise A2SError("truncated response")
        self.i += 1
        return self.d[self.i - 1]

    def short(self) -> int:
        return self.byte() | (self.byte() << 8)

    def string(self) -> str:
        end = self.d.find(b"\x00", self.i)
        if end < 0:
            raise A2SError("unterminated string")
        out = self.d[self.i : end].decode("utf-8", "replace")
        self.i = end + 1
        return out


def parse_info(data: bytes) -> ServerInfo:
    """Parse an A2S_INFO reply (source-style `I`)."""
    if len(data) < 6 or data[:4] != b"\xFF\xFF\xFF\xFF":
        raise A2SError("not a single-packet A2S reply")
    r = _Reader(data)
    r.i = 4
    if r.byte() != ord("I"):
        raise A2SError("unsupported A2S_INFO reply type")
    r.byte()                       # protocol
    name, mapname = r.string(), r.string()
    r.string(), r.string()         # folder, game
    r.short()                      # appid
    players, max_players, bots = r.byte(), r.byte(), r.byte()
    return ServerInfo(name, mapname, players, max_players, bots)


def query(ip: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> ServerInfo:
    """One A2S_INFO round-trip, answering a challenge if the server sends one."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(QUERY, (ip, port))
        data, _ = s.recvfrom(4096)
        if data[4:5] == b"A":                       # challenge -> retry with it
            s.sendto(QUERY + data[5:9], (ip, port))
            data, _ = s.recvfrom(4096)
        return parse_info(data)
    except socket.timeout as exc:
        raise A2SError("timeout") from exc
    except OSError as exc:
        raise A2SError(str(exc)) from exc
    finally:
        s.close()


def is_hltv(player_name: str) -> bool:
    """HLTV proxies name themselves "<server hostname> - HLTV"."""
    return HLTV_MARKER in player_name.upper()


def parse_players(data: bytes) -> list[str]:
    """Parse an A2S_PLAYER reply into connected player names."""
    if len(data) < 6 or data[:4] != b"\xFF\xFF\xFF\xFF" or data[4:5] != b"D":
        raise A2SError("not an A2S_PLAYER reply")
    r = _Reader(data)
    r.i = 5
    count = r.byte()
    names = []
    for _ in range(count):
        r.byte()                       # index
        names.append(r.string())
        r.i += 8                       # score (long) + duration (float)
        if r.i > len(r.d):
            raise A2SError("truncated player list")
    return names


def count_humans(names: list[str]) -> int:
    return sum(1 for n in names if not is_hltv(n))


def count_hltv(names: list[str]) -> int:
    """Proxies occupying player slots, so capacity can be reported honestly."""
    return sum(1 for n in names if is_hltv(n))


def query_players(ip: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> list[str]:
    """A2S_PLAYER, answering the challenge GoldSrc always sends for it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(PLAYER_QUERY, (ip, port))
        data, _ = s.recvfrom(4096)
        if data[4:5] == b"A":
            s.sendto(b"\xFF\xFF\xFF\xFFU" + data[5:9], (ip, port))
            data, _ = s.recvfrom(4096)
        return parse_players(data)
    except socket.timeout as exc:
        raise A2SError("timeout") from exc
    except OSError as exc:
        raise A2SError(str(exc)) from exc
    finally:
        s.close()
