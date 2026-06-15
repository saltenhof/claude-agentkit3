#!/usr/bin/env python3
"""
Test-only plain-HTTP harness wrapping ControlPlaneApplication.
NOT for production — transport only (plain HTTP, no auth middleware, no TLS).
The application logic, services, and SQLite persistence are REAL.

There is deliberately NO test-only story-seeding or status-bypass endpoint:
the AC14 e2e creates stories through the REAL PUBLIC create path
(POST /v1/projects/{key}/stories) with a valid typed reconciliation evidence
block (E4, AG3-093 R4), and reads them back through the PUBLIC search endpoint.
This harness only forwards plain HTTP to the real ControlPlaneApplication.

Usage:
  python python_harness.py [port]
  # Prints the actual bound port to stdout, then serves until killed.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Point to the real agentkit package
_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent  # T:/codebase/claude-agentkit3
sys.path.insert(0, str(_REPO_ROOT / "src"))

# Set AGENTKIT_STORE_DIR to a tmp dir for each test run.
# Force SQLite backend regardless of any environment configuration —
# the E2E test must use a real but isolated local store, never production Postgres.
_tmp_dir = tempfile.mkdtemp(prefix="ak3_e2e_")
os.environ["AGENTKIT_STORE_DIR"] = _tmp_dir
os.environ["AGENTKIT_STATE_BACKEND"] = "sqlite"
# AGENTKIT_ALLOW_SQLITE is required by the SQLite backend guard for non-unit-test paths.
# The harness is test-only and uses a real but isolated ephemeral SQLite store.
os.environ["AGENTKIT_ALLOW_SQLITE"] = "1"


def build_app() -> object:
    from agentkit.control_plane_http.app import (
        ControlPlaneApplication,
        ControlPlaneApplicationRoutes,
    )

    # Use NO auth middleware so the test can call endpoints directly
    return ControlPlaneApplication(routes=ControlPlaneApplicationRoutes())


def make_handler(app: object) -> type[BaseHTTPRequestHandler]:
    from agentkit.control_plane_http.app import ControlPlaneApplication as _App

    _app: _App = app  # type: ignore[assignment]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch()

        def do_PATCH(self) -> None:  # noqa: N802
            self._dispatch()

        def do_PUT(self) -> None:  # noqa: N802
            self._dispatch()

        def do_DELETE(self) -> None:  # noqa: N802
            self._dispatch()

        def _dispatch(self) -> None:
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_length) if content_length > 0 else b""
                response = _app.handle_request(
                    method=self.command,
                    path=self.path,
                    body=body,
                    request_headers=dict(self.headers.items()),
                )
                self.send_response(response.status_code)
                for key, value in response.headers:
                    self.send_header(key, value)
                if "content-type" not in {k.lower() for k, _ in response.headers}:
                    self.send_header("Content-Type", "application/json")
                # Always close the connection so Node.js fetch does not hang waiting
                # for keep-alive reuse on a single-threaded server.
                self.send_header("Connection", "close")
                if response.stream is None:
                    self.send_header("Content-Length", str(len(response.body)))
                    self.end_headers()
                    self.wfile.write(response.body)
                else:
                    self.end_headers()
                    for chunk in response.stream:
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except Exception as exc:  # noqa: BLE001
                # Guarantee a response so the client never sees a bare socket close.
                error_body = json.dumps({"error": f"Internal server error: {exc}"}).encode()
                try:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(error_body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(error_body)
                except Exception:  # noqa: BLE001
                    pass  # socket already gone — nothing to do

        def log_message(self, fmt: str, *args: object) -> None:  # noqa: D102
            pass  # suppress request logs during tests

    return Handler


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    app = build_app()
    handler = make_handler(app)
    # ThreadingHTTPServer: each request is handled in its own thread so that
    # HTTP/1.1 keep-alive connections from Node.js fetch do not deadlock against
    # a single-threaded server that is blocked waiting for the next request.
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    actual_port = server.server_address[1]
    # Print port to stdout so the test can read it
    print(actual_port, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
