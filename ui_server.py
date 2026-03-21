#!/usr/bin/env python3
"""
X-Ray Scanner — Web UI Server

Lightweight HTTP server that provides:
  - Static file serving (ui.html)
  - REST API for scanning directories
  - Directory browsing API
  - Settings management

Usage:
  python ui_server.py              # starts on http://localhost:8077
  python ui_server.py --port 9000  # custom port
"""

import argparse
import json
import logging
import platform
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

from services.app_state import state
from services.chat_engine import load_guide
from services.scan_manager import (
    get_rust_binary, _fwd, browse_directory, get_drives,
    scan_with_python, scan_with_rust, background_scan,
    count_scannable_files, execute_monkey_tests, execute_wire_test,
)
from services.git_analyzer import analyze_git_hotspots, parse_imports, run_ruff
from services.satd_scanner import scan_satd

# ── Backward compatibility aliases ───────────────────────────────────────
# Tests and external code import these names from ui_server directly.
_load_guide = load_guide
_fwd = _fwd  # re-export
_count_scannable_files = count_scannable_files
_background_scan = background_scan
_execute_monkey_tests = execute_monkey_tests
_execute_wire_test = execute_wire_test
scan_satd = scan_satd  # re-export
analyze_git_hotspots = analyze_git_hotspots  # re-export
parse_imports = parse_imports  # re-export


# Backward-compat: tests access module-level _last_scan_result etc.
# Python 3.7+ supports module-level __getattr__ and __setattr__ (PEP 562).
# However __setattr__ is not directly supported. We use a property-like wrapper.
# The simplest solution: make them real module attributes but keep them in sync.
_last_scan_result = None  # will be read/written by tests
_scan_progress = None


class _ModuleProxy:
    """Intercept attribute access on this module to keep state in sync."""
    _PROXIED = {"_last_scan_result", "_scan_progress"}

    def __init__(self, module):
        object.__setattr__(self, '_module', module)

    def __getattr__(self, name):
        if name == "_last_scan_result":
            return state.last_scan_result
        if name == "_scan_progress":
            return state.scan_progress
        return getattr(object.__getattribute__(self, '_module'), name)

    def __setattr__(self, name, value):
        if name == "_last_scan_result":
            state.last_scan_result = value
            return
        if name == "_scan_progress":
            state.scan_progress = value
            return
        setattr(object.__getattribute__(self, '_module'), name, value)


import sys as _sys
_sys.modules[__name__] = _ModuleProxy(_sys.modules[__name__])


# ── Collect route tables from api/ modules ───────────────────────────────

from api.scan_routes import GET_ROUTES as _scan_get, POST_ROUTES as _scan_post
from api.fix_routes import POST_ROUTES as _fix_post
from api.analysis_routes import POST_ROUTES as _analysis_post
from api.browse_routes import GET_ROUTES as _browse_get
from api.pm_routes import (
    GET_ROUTES as _pm_get, POST_ROUTES as _pm_post,
)

_GET_ROUTES: dict[str, object] = {}
_POST_ROUTES: dict[str, object] = {}

for table in (_scan_get, _browse_get, _pm_get):
    _GET_ROUTES.update(table)

for table in (_scan_post, _fix_post, _analysis_post, _pm_post):
    _POST_ROUTES.update(table)

logger = logging.getLogger(__name__)
ROOT = Path(__file__).parent


# ── HTTP Handler ─────────────────────────────────────────────────────────


class XRayHandler(BaseHTTPRequestHandler):
    """Handle API requests and serve the UI."""

    def log_message(self, format, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            logger.debug("Client connection lost during request")

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, filepath: Path):
        try:
            content = filepath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            logger.debug("UI file not found: %s", self.path)
            self.send_error(404, "File not found")

    _MAX_BODY = 10 * 1024 * 1024  # 10 MB safety limit

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        if length > self._MAX_BODY:
            self.send_error(413, "Request body too large")
            return {}
        body = self.rfile.read(length)
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}

    # ── GET dispatch ──────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Static routes
        if path in ("/", "/ui.html"):
            self._send_html(ROOT / "ui.html")
            return

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        # Dynamic GET routes
        handler_fn = _GET_ROUTES.get(path)
        if handler_fn:
            params = parse_qs(parsed.query)
            data, status = handler_fn(params, self)
            self._send_json(data, status)
            return

        self.send_error(404)

    # ── POST dispatch ─────────────────────────────────────────────────

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        handler_fn = _POST_ROUTES.get(path)
        if handler_fn:
            body = self._read_body()
            data, status = handler_fn(body, self)
            self._send_json(data, status)
            return

        self.send_error(404)


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="X-Ray Scanner Web UI")
    parser.add_argument("--port", "-p", type=int, default=8077, help="Port to listen on (default: 8077)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    args = parser.parse_args()

    # ── Environment verification ──────────────────────────────────────
    from xray.compat import check_environment, environment_summary

    ok, problems = check_environment()
    if problems:
        for p in problems:
            lvl = logging.ERROR if p.startswith("[REQUIRED]") else logging.WARNING
            logger.log(lvl, p)
    if not ok:
        raise SystemExit(1)
    logger.info("Environment OK:\n%s", environment_summary())

    load_guide()

    ServerClass = type(
        "ThreadedHTTPServer",
        (ThreadingMixIn, HTTPServer),
        {"daemon_threads": True, "allow_reuse_address": True},
    )
    try:
        server = ServerClass((args.host, args.port), XRayHandler)
    except OSError as e:
        logger.error("Cannot bind to %s:%s — %s", args.host, args.port, e)
        logger.error("Another instance is likely already running on that port.")
        logger.error("Kill it first or use: python ui_server.py --port %s", args.port + 1)
        raise SystemExit(1) from e

    rust_status = "available" if get_rust_binary() else "not built"
    logger.info("X-Ray Scanner UI: http://%s:%s", args.host, args.port)
    logger.info("  Python scanner: ready")
    logger.info("  Rust scanner:   %s", rust_status)
    logger.info("  Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
