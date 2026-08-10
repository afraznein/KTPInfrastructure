"""Bounded shutdown for the suite's loopback mock HTTP servers.

Both `stdlib` teardown calls a mock server makes can block forever:

  - `BaseServer.shutdown()` waits for `serve_forever()` to acknowledge, and
    returns only when that loop actually exits.
  - `ThreadingMixIn.server_close()` calls `self._threads.join()` with **no
    timeout**, and `block_on_close` defaults to True *independently of*
    `daemon_threads`.

A keep-alive handler thread sits in `recvfrom` until its peer closes the
connection. The suite's peer is hlds, which is still running when the mocks
are torn down — so both calls wedge, and the process never reaches interpreter
exit where daemon threads would have been reaped.

That is the whole reason a passing 295s suite occupied CI for its full 30-minute
ceiling on 2026-08-09/10: pytest printed its summary, then blocked in
`FakeRelay.stop()` until the job was killed, stranding hlds as an orphan.

⚠️ `daemon_threads = True` does NOT protect against this. It governs what
happens at *interpreter exit*; it says nothing about an explicit `join()` that
runs long before then. The relay had that flag and hung anyway.
"""
from __future__ import annotations

import threading
import warnings


def _run_quietly(fn):
    """Wrap `fn` so an exception in the helper thread can't spam stderr during
    teardown — a failure here is reported via the returned stall list."""
    def runner() -> None:
        try:
            fn()
        except Exception:
            pass
    return runner


def stop_server(server, thread, timeout: float = 2.0) -> list[str]:
    """Stop `server` without ever blocking indefinitely.

    Each potentially-blocking step runs on a daemon helper and is joined with
    `timeout`. Returns the labels of the steps that did not finish — empty
    means a clean stop. Callers surface a non-empty result rather than
    swallowing it, because the failure mode this replaces was invisible.
    """
    stalled: list[str] = []
    for label, fn in (("shutdown", server.shutdown),
                      ("server_close", server.server_close)):
        helper = threading.Thread(
            target=_run_quietly(fn), name=f"mock-stop-{label}", daemon=True
        )
        helper.start()
        helper.join(timeout)
        if helper.is_alive():
            stalled.append(label)

    if thread is not None:
        thread.join(timeout=timeout)
        if thread.is_alive():
            stalled.append("serve_forever")
    return stalled


def warn_if_stalled(name: str, stalled: list[str]) -> None:
    """Surface a stalled teardown as a pytest warning.

    Deliberately a warning and not an exception: a leaked mock thread is a
    diagnostic, not a reason to fail a green suite. Deliberately not silent
    either — silence is what let a wedged teardown read as a healthy run.
    """
    if not stalled:
        return
    warnings.warn(
        f"{name}: teardown did not complete within the timeout "
        f"({', '.join(stalled)} still running). A client is most likely still "
        f"holding a keep-alive connection. Threads are daemons so the "
        f"interpreter will still exit.",
        RuntimeWarning,
        stacklevel=2,
    )
