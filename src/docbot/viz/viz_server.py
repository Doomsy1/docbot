"""Replay server for pipeline visualization."""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tracker import PipelineTracker

from ._viz_html import VIZ_HTML, REPLAY_HTML


def start_viz_server(
    tracker: PipelineTracker,
    port: int = 0,
    open_browser: bool = True,
) -> HTTPServer:
    """Start the visualization HTTP server in a daemon thread.

    Returns the HTTPServer instance (whose .server_address gives the bound port).
    """

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/state":
                body = json.dumps(tracker.snapshot()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/" or self.path == "":
                body = VIZ_HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            # Silence request logging to avoid polluting Rich output.
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    actual_port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{actual_port}"
    if open_browser:
        webbrowser.open(url)

    return server, url


# ---------------------------------------------------------------------------
# Replay Server
# ---------------------------------------------------------------------------


def start_replay_server(
    events_path: Path,
    port: int = 8001,
    open_browser: bool = True,
) -> None:
    """Start the replay server with events from the given path."""

    if not events_path.exists():
        raise FileNotFoundError(f"Events file not found: {events_path}")

    events_data = json.loads(events_path.read_text(encoding="utf-8"))

    print(f"Starting replay server at http://127.0.0.1:{port}")
    print(f"Run ID: {events_data.get('run_id', 'unknown')}")
    print(f"Duration: {events_data.get('total_duration', 0):.1f}s")
    print(f"Events: {len(events_data.get('events', []))}")

    class ReplayHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/events":
                body = json.dumps(events_data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/" or self.path == "":
                body = REPLAY_HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    server = HTTPServer(("127.0.0.1", port), ReplayHandler)

    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}")

    print("Press Ctrl+C to stop the server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down replay server...")
        server.shutdown()
