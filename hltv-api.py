#!/usr/bin/env python3
"""
KTP HLTV Command API
Receives HTTP requests and writes commands to HLTV FIFO pipes.
Also supports restarting individual HLTV instances.

Location: /home/hltvserver/hltv-api.py (on data server)
Service: /etc/systemd/system/hltv-api.service

Endpoints:
  POST /hltv/<port>/command  - Send command to HLTV via FIFO pipe
  POST /hltv/<port>/restart  - Restart specific HLTV instance
  GET  /health               - Health check
"""

import os
import json
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

API_PORT = 8087
AUTH_KEY = "KTPVPS2026"
PIPE_DIR = "/home/hltvserver/cmdpipes"
VALID_PORTS = range(27020, 27045)

class HLTVHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[HLTV-API] {args[0]}")

    def send_json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_POST(self):
        # Auth check
        auth = self.headers.get("X-Auth-Key", "")
        if auth != AUTH_KEY:
            self.send_json(401, {"error": "Unauthorized"})
            return

        # Parse path: /hltv/<port>/<action>
        parts = self.path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "hltv":
            self.send_json(400, {"error": "Invalid path. Use /hltv/<port>/command or /hltv/<port>/restart"})
            return

        try:
            port = int(parts[1])
        except ValueError:
            self.send_json(400, {"error": "Invalid port number"})
            return

        if port not in VALID_PORTS:
            self.send_json(400, {"error": f"Port must be 27020-27044"})
            return

        action = parts[2]

        if action == "command":
            self.handle_command(port)
        elif action == "restart":
            self.handle_restart(port)
        else:
            self.send_json(400, {"error": f"Unknown action: {action}"})

    def handle_command(self, port):
        """Send command to HLTV via FIFO pipe"""
        # Read command from body
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

        # Write to FIFO
        pipe_path = f"{PIPE_DIR}/hltv-{port}.pipe"
        if not os.path.exists(pipe_path):
            self.send_json(500, {"error": f"Pipe not found: {pipe_path}"})
            return

        try:
            with open(pipe_path, "w") as f:
                f.write(command + "\n")
                f.flush()
            self.send_json(200, {"success": True, "port": port, "command": command})
            print(f"[HLTV-API] Sent to {port}: {command}")
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def handle_restart(self, port):
        """Restart specific HLTV instance via systemctl"""
        service_name = f"hltv@{port}"
        print(f"[HLTV-API] Restarting {service_name}...")

        try:
            result = subprocess.run(
                ["systemctl", "restart", service_name],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                self.send_json(200, {
                    "success": True,
                    "port": port,
                    "message": f"HLTV {port} restarted successfully"
                })
                print(f"[HLTV-API] Restarted {service_name} successfully")
            else:
                self.send_json(500, {
                    "success": False,
                    "port": port,
                    "error": result.stderr.strip() or "Unknown error"
                })
                print(f"[HLTV-API] Failed to restart {service_name}: {result.stderr}")

        except subprocess.TimeoutExpired:
            self.send_json(500, {"error": "Restart timed out"})
            print(f"[HLTV-API] Restart of {service_name} timed out")
        except Exception as e:
            self.send_json(500, {"error": str(e)})
            print(f"[HLTV-API] Error restarting {service_name}: {e}")

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok"})
        else:
            self.send_json(404, {"error": "Not found"})

if __name__ == "__main__":
    print(f"[HLTV-API] Starting on port {API_PORT}")
    print(f"[HLTV-API] Endpoints:")
    print(f"[HLTV-API]   POST /hltv/<port>/command - Send command to HLTV")
    print(f"[HLTV-API]   POST /hltv/<port>/restart - Restart HLTV instance")
    print(f"[HLTV-API]   GET  /health - Health check")
    server = HTTPServer(("0.0.0.0", API_PORT), HLTVHandler)
    server.serve_forever()
