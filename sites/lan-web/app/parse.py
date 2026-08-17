"""Turning a string into an int, without isdigit() lying about it.

isdigit() is true for every Unicode digit, and int() then splits two ways, both
bad: '²' (category No) RAISES, and '٠' or '1٢3' (category Nd) SUCCEED as 0 and
123 — values nobody typed, written straight into a discord_id. So the guard has
to be isascii(), not isdecimal(); rejecting only what crashes leaves the silent
half.

Imports nothing from the app on purpose: config.py loads before everything and
still has to parse the admin allowlist."""
from __future__ import annotations


def as_int(raw, default=None):
    """The string as an int, or `default` if it is not a plain ASCII integer."""
    s = (raw or "").strip()
    return int(s) if s.isascii() and s.isdigit() else default


def snowflake(raw) -> int | None:
    """A Discord id, or None."""
    return as_int(raw)


def is_snowflake(raw) -> bool:
    """Whether Discord could read `raw` as an id. For the callers that keep the
    string rather than the int — a snowflake outruns a signed 64-bit int."""
    return as_int(raw) is not None


def bounded(raw, lo: int, hi: int, default=None):
    """An int inside [lo, hi] inclusive, or `default`."""
    n = as_int(raw)
    return n if n is not None and lo <= n <= hi else default
