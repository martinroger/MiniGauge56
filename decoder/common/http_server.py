"""MiniGauge HTTP Server & Base Request Handler.

Provides reusable HTTP request handling, static asset streaming,
MIME resolution, CORS configuration, template rendering, port discovery,
and browser lifecycle management for the MiniGauge offline toolset.
Zero pip dependencies (Python 3 stdlib only).
"""

import json
import os
import socket
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

try:
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
except ImportError:  # Fallback for minimal Python environments
    from http.server import HTTPServer as ThreadingHTTPServer, BaseHTTPRequestHandler

SCRIPT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = SCRIPT_DIR / "web" / "static"
TEMPLATES_DIR = SCRIPT_DIR / "web" / "templates"

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".csv": "text/csv; charset=utf-8",
    ".bin": "application/octet-stream",
}


class BaseAppHandler(BaseHTTPRequestHandler):
    """Reusable HTTP handler base class providing JSON, static assets, and template helpers."""

    # Set to True in subclasses or via CLI to enable verbose HTTP logging
    verbose_logging: bool = False

    def log_message(self, format: str, *args: Any) -> None:
        """Silences spammy HTTP access logs unless verbose_logging is enabled."""
        if self.verbose_logging:
            super().log_message(format, *args)

    def parse_query(self) -> Tuple[str, Dict[str, List[str]]]:
        """Parses the request URL path and query string parameters."""
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        return parsed.path, query

    def get_query_param(self, name: str, default: str = "") -> str:
        """Extracts a single string query parameter value."""
        _, query = self.parse_query()
        values = query.get(name, [])
        return values[0] if values else default

    def read_json_body(self) -> Dict[str, Any]:
        """Reads and parses the JSON request body using Content-Length."""
        length_header = self.headers.get("Content-Length", 0)
        try:
            length = int(length_header)
        except ValueError:
            length = 0

        if length <= 0:
            return {}

        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def send_json(self, data: Any, status: int = 200, headers: Optional[Dict[str, str]] = None) -> None:
        """Serializes and sends a JSON payload with CORS and Content-Length headers."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html: str, status: int = 200) -> None:
        """Sends an HTML response with UTF-8 encoding."""
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, rel_path: str) -> bool:
        """Safely serves a static file from STATIC_DIR. Returns False if file not found."""
        clean_rel = rel_path.lstrip("/")
        if clean_rel.startswith("static/"):
            clean_rel = clean_rel[len("static/") :]

        target = (STATIC_DIR / clean_rel).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(403, "Access Denied")
            return True

        if not target.is_file():
            return False

        mime = MIME_TYPES.get(target.suffix.lower(), "application/octet-stream")
        data = target.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)
        return True

    def render_template(self, template_name: str, context: Optional[Dict[str, str]] = None) -> str:
        """Reads an HTML template from TEMPLATES_DIR and performs simple string substitutions."""
        target = TEMPLATES_DIR / template_name
        if not target.is_file():
            raise FileNotFoundError(f"Template not found: {template_name}")

        content = target.read_text(encoding="utf-8")
        if context:
            for k, v in context.items():
                content = content.replace(f"{{{{{k}}}}}", str(v))
        return content

    def do_OPTIONS(self) -> None:
        """Handles CORS preflight requests."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Checks if a TCP port is currently bound on host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def find_available_port(start_port: int, max_attempts: int = 50, host: str = "127.0.0.1") -> int:
    """Finds the first available TCP port starting from start_port."""
    port = start_port
    for _ in range(max_attempts):
        if not is_port_in_use(port, host):
            return port
        port += 1
    raise RuntimeError(f"Could not find an available TCP port in range {start_port}..{start_port + max_attempts}")


def start_server(
    handler_cls: Type[BaseAppHandler],
    port: int = 8080,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    browser_delay_s: float = 0.5,
    server_name: str = "MiniGauge Tool",
) -> None:
    """Starts the HTTP server, launches default browser, and blocks until interrupted."""
    server = None
    active_port = port
    for _ in range(50):
        try:
            server = ThreadingHTTPServer((host, active_port), handler_cls)
            break
        except OSError:
            active_port += 1

    if server is None:
        raise RuntimeError(f"Could not bind to port {port} or subsequent 50 ports.")

    if active_port != port:
        print(f"[!] Port {port} is occupied. Using next available port: {active_port}", flush=True)

    url = f"http://{host}:{active_port}/"

    print(f"==================================================", flush=True)
    print(f"  {server_name}", flush=True)
    print(f"  Listening on: {url}", flush=True)
    print(f"  Static assets: {STATIC_DIR}", flush=True)
    print(f"  Templates:     {TEMPLATES_DIR}", flush=True)
    print(f"  Press Ctrl+C to terminate.", flush=True)
    print(f"==================================================", flush=True)

    if open_browser:
        def _launch():
            time.sleep(browser_delay_s)
            webbrowser.open(url)

        t = threading.Thread(target=_launch, daemon=True)
        t.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n[+] Shutting down {server_name}...")
    finally:
        server.server_close()
