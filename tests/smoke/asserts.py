"""High-level assertions for smoke tests.

Each function raises AssertionError on failure with a concrete message naming
the missing / failed entries — never just "False". Designed so test output
points the reader straight at the broken module/plugin.
"""

from __future__ import annotations

from .parse import (
    ModuleRow,
    PluginRow,
    matches_truncated,
    normalise_module_name,
    normalise_plugin_name,
    parse_modules,
    parse_plugins,
)
from .server_handle import ServerHandle


def assert_modules_loaded(
    handle: ServerHandle,
    expected: list[str],
    *,
    require_running: bool = True,
) -> list[ModuleRow]:
    """Assert every name in `expected` appears in `amx modules` output.

    Names are matched after normalisation, so `amxxcurl`, `amxxcurl_ktp`, and
    `amxxcurl_ktp_i386.so` all match the same row.

    Returns the parsed rows on success.
    """
    output = handle.rcon("amx modules")
    rows = parse_modules(output)
    by_key = {normalise_module_name(r.name): r for r in rows}

    missing: list[str] = []
    not_running: list[tuple[str, str]] = []
    for name in expected:
        key = normalise_module_name(name)
        row = by_key.get(key)
        if row is None:
            missing.append(name)
        elif require_running and not row.is_running:
            not_running.append((name, row.status))

    problems: list[str] = []
    if missing:
        problems.append(
            f"missing modules: {', '.join(missing)}\n"
            f"loaded ({len(rows)}): {', '.join(r.name for r in rows)}"
        )
    if not_running:
        details = ", ".join(f"{n}={s}" for n, s in not_running)
        problems.append(f"modules not running: {details}")
    if problems:
        raise AssertionError("\n".join(problems))
    return rows


def assert_plugins_running(
    handle: ServerHandle,
    expected: list[str],
) -> list[PluginRow]:
    """Assert every name in `expected` appears in `amx plugins` output with
    status=running. Matching is truncation-aware — AMXX prints the .amxx
    filename truncated to 11 chars, so we match expected vs actual on a
    leading-prefix basis."""
    output = handle.rcon("amx plugins")
    rows = parse_plugins(output)

    missing: list[str] = []
    not_running: list[tuple[str, str]] = []
    for name in expected:
        match = next(
            (
                r for r in rows
                if matches_truncated(name, r.filename)
                or matches_truncated(name, r.name)
            ),
            None,
        )
        if match is None:
            missing.append(name)
        elif not match.is_running:
            not_running.append((name, match.status))

    problems: list[str] = []
    if missing:
        problems.append(
            f"missing plugins: {', '.join(missing)}\n"
            f"loaded ({len(rows)}): {', '.join(r.filename for r in rows)}"
        )
    if not_running:
        details = ", ".join(f"{n}={s}" for n, s in not_running)
        problems.append(f"plugins not running: {details}")
    if problems:
        raise AssertionError("\n".join(problems))
    return rows


def assert_no_failed_modules(handle: ServerHandle) -> list[ModuleRow]:
    """Catch the 04-14 KTPAmxxCurl class: a module silently fails to load.

    Zero parsed rows is a FAILURE, not a pass: if the KTPAMXX core .so never
    loaded, `amx modules` returns "Unknown command", parse yields nothing, and
    the old gate printed "OK: no failed modules (0)" — the exact catastrophe
    this assert exists to catch, reported as green.
    """
    output = handle.rcon("amx modules")
    rows = parse_modules(output)
    if not rows:
        raise AssertionError(
            "amx modules returned ZERO parseable rows — KTPAMXX core likely "
            f"never loaded (raw output: {output[:200]!r})"
        )
    failed = [r for r in rows if r.status.lower() not in ("running", "loaded")]
    if failed:
        details = ", ".join(f"{r.name}={r.status}" for r in failed)
        raise AssertionError(f"modules in non-running state: {details}")
    return rows


def assert_no_failed_plugins(handle: ServerHandle) -> list[PluginRow]:
    """Catch silent plugin load failures.

    Zero parsed rows fails for the same reason as assert_no_failed_modules —
    an empty listing means the platform is down, not that nothing failed.
    """
    output = handle.rcon("amx plugins")
    rows = parse_plugins(output)
    if not rows:
        raise AssertionError(
            "amx plugins returned ZERO parseable rows — KTPAMXX core likely "
            f"never loaded (raw output: {output[:200]!r})"
        )
    failed = [r for r in rows if not r.is_running]
    if failed:
        details = ", ".join(f"{r.filename}={r.status}" for r in failed)
        raise AssertionError(f"plugins in non-running state: {details}")
    return rows
