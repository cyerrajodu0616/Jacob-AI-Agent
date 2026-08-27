"""Local stand-in for the platform-infra Valkey read endpoint, for eval runs.

Speaks exactly the wire shape appstate/platform.py sends — POST
/infra/database/redis/update with {"redisKeyName": <arcId>, "operationType":
"retrieve", ...} — and answers from evals/fixtures.py. The sweep points the
agent's appstate subprocess here via JACOB_PLATFORM_BASE_URL, so a full-stack
eval exercises the real agent → MCP → platform-client → projection path with
ZERO contact with the real platform (prod or dev).

Behavior:
  known arcId   → 200 {"data": <memapp>}
  unknown arcId → 200 {"data": null}          (platform "no record" shape)
  ERROR_ARCID   → 500                          (transport-failure path)

Run standalone:  python -m evals.mockplatform [--port 8977]
In-process:      serve_in_thread() → (base_url, server) — used by evals/sweep.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .fixtures import ERROR_ARCID, FIXTURES


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — http.server naming
        if self.path == "/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self.path.endswith("/infra/database/redis/update"):
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            self._send(400, {"error": "bad payload"})
            return
        key = str(payload.get("redisKeyName") or "")
        if key == ERROR_ARCID:
            self._send(500, {"error": "synthetic platform failure"})
            return
        self._send(200, {"data": FIXTURES.get(key)})

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # quiet; stderr only when asked
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)


def serve_in_thread(port: int = 0) -> tuple[str, ThreadingHTTPServer]:
    """Start the mock on 127.0.0.1 (port 0 = OS-assigned) in a daemon thread.
    Returns (base_url, server); call server.shutdown() when done."""
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8977)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    url, _server = serve_in_thread(args.port)
    print(f"mock platform serving {len(FIXTURES)} fixtures at {url}")
    threading.Event().wait()  # foreground forever


if __name__ == "__main__":
    main()
