#!/usr/bin/env python3
"""
KTP HLTV Command API
Receives HTTP requests and writes commands to HLTV FIFO pipes.
Also supports restarting individual HLTV instances and querying recording state.

Location: /home/hltvserver/hltv-api.py (on data server)
Service: /etc/systemd/system/hltv-api.service

Endpoints:
  POST /hltv/<port>/command  - Send command to HLTV via FIFO pipe
  POST /hltv/<port>/restart  - Restart specific HLTV instance
  GET  /hltv/<port>/state    - Recording state from journalctl (v2.2)
  GET  /health               - Health check

v2.2 - 2026-04-28: Added /state endpoint for plugin polling. Fixes record-while-
                   recording bleed where HLTV silently ignored mid-recording
                   `record <new>` commands and kept original basename across
                   match/half boundaries.
v2.0 - 2026-01-18: Added ThreadingHTTPServer and timeouts to prevent hangs
"""

import os
import re
import json
import time
import subprocess
import socket
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

API_PORT = 8087
AUTH_KEY = "KTPVPS2026"
PIPE_DIR = "/home/hltvserver/cmdpipes"
VALID_PORTS = range(27020, 27045)

PIPE_WRITE_TIMEOUT = 5

# /state journal scan window. The 2026-05-04 forensics on ATL1 disproved the
# original assumption that HLTV emits "Length N sec." progress lines every
# ~60s on its own — those lines only appear in response to external rcon
# `status` calls. So `_parse_state()` now writes `status\n` to the cmdpipe
# itself before scanning the journal (see `_trigger_status_rcon` below), and
# this 5-min window only needs to be wide enough to absorb journalctl write
# latency + our trigger sleep. Conservative for safety.
STATE_JOURNAL_WINDOW = "5 minutes ago"
STATE_JOURNALCTL_TIMEOUT = 4

# How long to wait between writing `status\n` to the cmdpipe and reading the
# journal back. HLTV processes one stdin line per tick (~10ms), the kernel
# flushes journald within ~50ms, but allow generous slack on a busy data
# server. Cost: this much added latency per /state call (which fires once
# per match start, per host — ~10x/day fleet-wide; not a hot path).
STATE_TRIGGER_SLEEP_SEC = 0.25

# Regexes against the message portion (after "hltv-wrapper.sh[PID]: ") of each
# journal line. Order matters during the newest-first walk in _parse_state().
_RE_START_RECORDING = re.compile(r"Start recording to (?P<basename>.+?)\.dem\.")
_RE_ALREADY_RECORDING = re.compile(r"Already recording to (?P<basename>.+?)\.dem\.")
_RE_COMPLETED_DEMO = re.compile(r"Completed demo (?P<basename>.+?)\.dem\.")
_RE_RECORDING_LENGTH = re.compile(r"Recording to (?P<basename>.+?)\.dem, Length")

# `journalctl --output=short-iso` emits "2026-04-28T12:42:02-04:00 host unit[pid]: msg"
# Note: Python 3.7+ strptime accepts both -0400 and -04:00 for %z.
_RE_JOURNAL_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:?\d{2})\s+\S+\s+\S+:\s+(?P<msg>.*)$"
)


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in separate threads to prevent blocking"""
    daemon_threads = True

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()


def _parse_iso(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")


def _service_active(port):
    """Returns True if hltv@<port>.service is currently active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", f"hltv@{port}.service"],
            capture_output=True, text=True, timeout=3,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def _trigger_status_rcon(port):
    """Write `status\\n` to HLTV's cmdpipe to trigger a fresh `Recording to ...
    Length N sec.` line in the journal.

    The HLTV `status` rcon prints recording state as a side effect; in v1.7.0
    F+A architecture (HLTV-cfg-driven `record auto_<friendly>`), the journal
    has no other periodic source for this signal — so without this trigger,
    the journal scan in _parse_state() returns recording=False whenever the
    last 5 minutes had no rcon-status traffic, producing false-positive
    "HLTV up but not recording" alerts at every match start (Bug 2, observed
    on ATL1 four times on 2026-05-03).

    Pipe write is non-blocking; failures are silent (caller falls back to
    journal-only scan, which is the prior buggy behavior). Pipe is a kernel
    FIFO — concurrent writes serialize at line granularity, so concurrent
    /state calls don't garble each other's `status` lines.
    """
    pipe_path = f"{PIPE_DIR}/hltv-{port}.pipe"
    if not os.path.exists(pipe_path):
        return False
    try:
        fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, b"status\n")
        finally:
            os.close(fd)
        return True
    except (BlockingIOError, OSError):
        return False


def _parse_state(port):
    """Parse last 5 minutes of journalctl for hltv@<port> and return state dict.

    Returns:
        {
          "recording": bool,
          "basename": str|null,        # demo basename without .dem suffix
          "process_running": bool,
          "last_event": {"type": str, "age_sec": int}|null,
          "already_recording_warning": bool,  # true if last event was "Already recording"
        }
    """
    process_running = _service_active(port)

    if not process_running:
        return {
            "recording": False,
            "basename": None,
            "process_running": False,
            "last_event": None,
            "already_recording_warning": False,
        }

    # Bug 2 fix (2026-05-04): trigger a fresh `status` rcon before scanning
    # the journal. See _trigger_status_rcon() docstring for rationale.
    _trigger_status_rcon(port)
    time.sleep(STATE_TRIGGER_SLEEP_SEC)

    try:
        result = subprocess.run(
            [
                "journalctl",
                "-u", f"hltv@{port}.service",
                "--since", STATE_JOURNAL_WINDOW,
                "--no-pager",
                "-q",
                "--output=short-iso",
            ],
            capture_output=True, text=True, timeout=STATE_JOURNALCTL_TIMEOUT,
        )
        lines = result.stdout.splitlines()
    except subprocess.TimeoutExpired:
        # Don't pretend we know — return safe "unknown but process is up" state.
        # Plugin treats this as idle (best-effort) so it doesn't infinite-poll.
        return {
            "recording": False,
            "basename": None,
            "process_running": True,
            "last_event": None,
            "already_recording_warning": False,
            "error": "journalctl timeout",
        }
    except Exception as e:
        return {
            "recording": False,
            "basename": None,
            "process_running": True,
            "last_event": None,
            "already_recording_warning": False,
            "error": str(e),
        }

    # Walk newest-first; first matching event wins.
    now = datetime.now(timezone.utc)
    for raw in reversed(lines):
        m = _RE_JOURNAL_LINE.match(raw)
        if not m:
            continue
        msg = m.group("msg")
        ts = m.group("ts")

        for kind, regex in (
            ("already_recording", _RE_ALREADY_RECORDING),
            ("start_recording", _RE_START_RECORDING),
            ("completed_demo", _RE_COMPLETED_DEMO),
            ("recording_length", _RE_RECORDING_LENGTH),
        ):
            mm = regex.search(msg)
            if not mm:
                continue
            try:
                age_sec = int((now - _parse_iso(ts)).total_seconds())
            except Exception:
                age_sec = -1
            basename = mm.groupdict().get("basename")
            recording = kind != "completed_demo"
            return {
                "recording": recording,
                "basename": basename if recording else None,
                "process_running": True,
                "last_event": {"type": kind, "age_sec": age_sec},
                "already_recording_warning": kind == "already_recording",
            }

    # No relevant events in the window — process is up but idle.
    return {
        "recording": False,
        "basename": None,
        "process_running": True,
        "last_event": None,
        "already_recording_warning": False,
    }


class HLTVHandler(BaseHTTPRequestHandler):
    timeout = 10

    def log_message(self, format, *args):
        print(f"[HLTV-API] {args[0]}")

    def send_json(self, code, data):
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _check_auth(self):
        auth = self.headers.get("X-Auth-Key", "")
        if auth != AUTH_KEY:
            self.send_json(401, {"error": "Unauthorized"})
            return False
        return True

    def _parse_path(self):
        """Returns (port, action) or (None, None) if path was rejected."""
        parts = self.path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "hltv":
            self.send_json(400, {"error": "Invalid path"})
            return None, None
        try:
            port = int(parts[1])
        except ValueError:
            self.send_json(400, {"error": "Invalid port number"})
            return None, None
        if port not in VALID_PORTS:
            self.send_json(400, {"error": "Port must be 27020-27044"})
            return None, None
        return port, parts[2]

    def do_POST(self):
        if not self._check_auth():
            return
        port, action = self._parse_path()
        if port is None:
            return
        if action == "command":
            self.handle_command(port)
        elif action == "restart":
            self.handle_restart(port)
        else:
            self.send_json(400, {"error": f"Unknown action: {action}"})

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok"})
            return
        # Auth required for /state
        if not self._check_auth():
            return
        port, action = self._parse_path()
        if port is None:
            return
        if action == "state":
            self.handle_state(port)
        else:
            self.send_json(400, {"error": f"Unknown GET action: {action}"})

    def handle_command(self, port):
        """Send command to HLTV via FIFO pipe"""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self.send_json(400, {"error": "No command provided"})
            return

        body = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(body)
            command = data.get("command", "").strip()
        except json.JSONDecodeError:
            command = body.strip()

        if not command:
            self.send_json(400, {"error": "Empty command"})
            return

        pipe_path = f"{PIPE_DIR}/hltv-{port}.pipe"
        if not os.path.exists(pipe_path):
            self.send_json(500, {"error": f"Pipe not found: {pipe_path}"})
            return

        try:
            fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
            try:
                os.write(fd, (command + "\n").encode())
            finally:
                os.close(fd)
            self.send_json(200, {"success": True, "port": port, "command": command})
            print(f"[HLTV-API] Sent to {port}: {command}")
        except BlockingIOError:
            self.send_json(500, {"error": f"Pipe {port} not ready (no reader)"})
            print(f"[HLTV-API] Pipe {port} blocked - no reader")
        except Exception as e:
            self.send_json(500, {"error": str(e)})
            print(f"[HLTV-API] Error writing to pipe {port}: {e}")

    def handle_restart(self, port):
        """Restart specific HLTV instance via systemctl"""
        service_name = f"hltv@{port}"
        print(f"[HLTV-API] Restarting {service_name}...")

        try:
            result = subprocess.run(
                ["systemctl", "restart", service_name],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                self.send_json(200, {
                    "success": True,
                    "port": port,
                    "message": f"HLTV {port} restarted successfully",
                })
                print(f"[HLTV-API] Restarted {service_name} successfully")
            else:
                self.send_json(500, {
                    "success": False,
                    "port": port,
                    "error": result.stderr.strip() or "Unknown error",
                })
                print(f"[HLTV-API] Failed to restart {service_name}: {result.stderr}")
        except subprocess.TimeoutExpired:
            self.send_json(500, {"error": "Restart timed out"})
            print(f"[HLTV-API] Restart of {service_name} timed out")
        except Exception as e:
            self.send_json(500, {"error": str(e)})
            print(f"[HLTV-API] Error restarting {service_name}: {e}")

    def handle_state(self, port):
        """Return current recording state from journalctl scan."""
        state = _parse_state(port)
        self.send_json(200, state)


if __name__ == "__main__":
    print(f"[HLTV-API] Starting on port {API_PORT} (threaded, v2.2)")
    print(f"[HLTV-API] Endpoints:")
    print(f"[HLTV-API]   POST /hltv/<port>/command - Send command to HLTV")
    print(f"[HLTV-API]   POST /hltv/<port>/restart - Restart HLTV instance")
    print(f"[HLTV-API]   GET  /hltv/<port>/state   - Recording state")
    print(f"[HLTV-API]   GET  /health              - Health check")
    server = ThreadingHTTPServer(("0.0.0.0", API_PORT), HLTVHandler)
    server.serve_forever()
