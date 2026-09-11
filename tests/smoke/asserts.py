"""High-level assertions for smoke tests.

Each function raises AssertionError on failure with a concrete message naming
the missing / failed entries — never just "False". Designed so test output
points the reader straight at the broken module/plugin.

AssertionError means "the thing under test is broken". InfrastructureFault
means "something else in the shared base image is broken" — see its docstring
for why the two must not share an exit code.
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


class InfrastructureFault(Exception):
    """Something in the shared runtime image is broken, and it is not the
    change under test.

    smoke-callable.yml is a reusable workflow: the red check lands on the
    caller's PR, including repos we do not own. A plugin that the base image
    failed to ship is our fault, not theirs, and reporting it through the same
    channel as a real regression makes the gate unable to tell the two apart.

    Raised only when an under-test set was supplied — with no such set there is
    nothing to attribute against and every failure stays an AssertionError.
    """


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


def _raise_by_attribution(
    failed: list[tuple[str, str, bool]],
    under_test: list[str] | None,
    noun: str,
) -> None:
    """Route a non-empty failure list to the right exception.

    Anything flagged as under test stays an AssertionError. With no under-test
    set supplied, everything does — that is the pre-existing contract and the
    default every non-smoke caller gets.
    """
    if not failed:
        return
    details = ", ".join(f"{label}={status}" for label, status, _ in failed)
    if under_test is None:
        raise AssertionError(f"{noun} in non-running state: {details}")

    mine = [f"{label}={status}" for label, status, is_mine in failed if is_mine]
    if mine:
        raise AssertionError(
            f"{noun} in non-running state (UNDER TEST): {', '.join(mine)}\n"
            f"all non-running {noun}: {details}"
        )
    raise InfrastructureFault(
        f"{noun} in non-running state, none of them under test "
        f"({', '.join(under_test)}): {details}"
    )


def assert_no_failed_modules(
    handle: ServerHandle,
    under_test: list[str] | None = None,
) -> list[ModuleRow]:
    """Catch the 04-14 KTPAmxxCurl class: a module silently fails to load.

    Zero parsed rows is a FAILURE, not a pass: if the KTPAMXX core .so never
    loaded, `amx modules` returns "Unknown command", parse yields nothing, and
    the old gate printed "OK: no failed modules (0)" — the exact catastrophe
    this assert exists to catch, reported as green. That stays fatal whatever
    `under_test` says: with no module listing at all, the under-test artifact
    is demonstrably not running either.
    """
    output = handle.rcon("amx modules")
    rows = parse_modules(output)
    if not rows:
        raise AssertionError(
            "amx modules returned ZERO parseable rows — KTPAMXX core likely "
            f"never loaded (raw output: {output[:200]!r})"
        )
    wanted = {normalise_module_name(n) for n in (under_test or ())}
    failed = [
        (r.name, r.status, normalise_module_name(r.name) in wanted)
        for r in rows
        if r.status.lower() not in ("running", "loaded")
    ]
    _raise_by_attribution(failed, under_test, "modules")
    return rows


def assert_no_failed_plugins(
    handle: ServerHandle,
    under_test: list[str] | None = None,
) -> list[PluginRow]:
    """Catch silent plugin load failures.

    Zero parsed rows fails for the same reason as assert_no_failed_modules —
    an empty listing means the platform is down, not that nothing failed.

    A `bad load` row carries `unknown` in every column except the filename, so
    attribution matches on the filename AMXX truncates to 11 chars.
    """
    output = handle.rcon("amx plugins")
    rows = parse_plugins(output)
    if not rows:
        raise AssertionError(
            "amx plugins returned ZERO parseable rows — KTPAMXX core likely "
            f"never loaded (raw output: {output[:200]!r})"
        )
    def _mine(row: PluginRow) -> bool:
        return any(
            matches_truncated(name, row.filename) or matches_truncated(name, row.name)
            for name in (under_test or ())
        )

    failed = [
        (r.filename, r.status, _mine(r)) for r in rows if not r.is_running
    ]
    _raise_by_attribution(failed, under_test, "plugins")
    return rows
