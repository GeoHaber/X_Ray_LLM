"""
HTTP Integration Tests — spin up a real server and verify API responses.

These tests start XRayHandler on a random free port, send actual HTTP
requests, and validate the responses. They prove that routing, JSON
serialisation, and error handling work end-to-end.

Run:  python -m pytest tests/test_http_integration.py -v --tb=short
"""

import json
import os
import sys
import threading
import time
from http.client import HTTPConnection
from http.server import HTTPServer
from socketserver import ThreadingMixIn

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from ui_server import XRayHandler

# ── Fixture: ephemeral HTTP server ──────────────────────────────────────


class _TestServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@pytest.fixture(scope="module")
def server():
    """Start a real HTTP server on a free port and yield (host, port)."""
    srv = _TestServer(("127.0.0.1", 0), XRayHandler)
    host, port = srv.server_address
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    # Wait until the server is ready
    for _ in range(20):
        try:
            conn = HTTPConnection(host, port, timeout=2)
            conn.request("GET", "/favicon.ico")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    yield host, port
    srv.shutdown()


def _get(server, path):
    """Helper: GET request, return (status, parsed_json_or_None, body_bytes)."""
    host, port = server
    conn = HTTPConnection(host, port, timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = None
    return resp.status, data, body


def _post(server, path, payload=None):
    """Helper: POST JSON request, return (status, parsed_json)."""
    host, port = server
    conn = HTTPConnection(host, port, timeout=30)
    body = json.dumps(payload or {}).encode("utf-8")
    conn.request(
        "POST", path, body=body, headers={"Content-Type": "application/json", "Content-Length": str(len(body))}
    )
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = None
    return resp.status, data


# ══════════════════════════════════════════════════════════════════════════
# 1. Static routes
# ══════════════════════════════════════════════════════════════════════════


class TestStaticRoutes:
    def test_root_serves_html(self, server):
        status, _, body = _get(server, "/")
        assert status == 200
        assert b"<!DOCTYPE html>" in body or b"<html" in body

    def test_ui_html_serves_html(self, server):
        status, _, body = _get(server, "/ui.html")
        assert status == 200
        assert b"<html" in body

    def test_favicon_returns_204(self, server):
        status, _, _ = _get(server, "/favicon.ico")
        assert status == 204

    def test_404_on_unknown_path(self, server):
        status, _, _ = _get(server, "/nonexistent")
        assert status == 404


# ══════════════════════════════════════════════════════════════════════════
# 2. Browse / info APIs
# ══════════════════════════════════════════════════════════════════════════


class TestBrowseAPI:
    def test_browse_returns_json(self, server):
        status, data, _ = _get(server, f"/api/browse?path={REPO_ROOT}")
        assert status == 200
        assert "items" in data

    def test_browse_missing_path(self, server):
        status, data, _ = _get(server, "/api/browse")
        # Should still return something — maybe current dir or error
        assert status in (200, 400)

    def test_info_returns_json(self, server):
        status, data, _ = _get(server, "/api/info")
        assert status == 200
        assert isinstance(data, dict)

    def test_env_check(self, server):
        status, data, _ = _get(server, "/api/env-check")
        assert status == 200
        assert "ok" in data or "status" in data or "python" in data

    def test_dependency_check(self, server):
        status, data, _ = _get(server, "/api/dependency-check")
        assert status == 200
        assert isinstance(data, dict)


# ══════════════════════════════════════════════════════════════════════════
# 3. Analysis API endpoints
# ══════════════════════════════════════════════════════════════════════════


class TestAnalysisAPI:
    def test_smells_endpoint(self, server):
        status, data = _post(server, "/api/smells", {"directory": REPO_ROOT})
        assert status == 200
        assert isinstance(data, dict)

    def test_dead_code_endpoint(self, server):
        status, data = _post(server, "/api/dead-code", {"directory": REPO_ROOT})
        assert status == 200
        assert isinstance(data, dict)

    def test_duplicates_endpoint(self, server):
        status, data = _post(server, "/api/duplicates", {"directory": REPO_ROOT})
        assert status == 200
        assert isinstance(data, dict)

    def test_format_endpoint(self, server):
        status, data = _post(server, "/api/format", {"directory": REPO_ROOT})
        assert status == 200
        assert isinstance(data, dict)

    def test_health_endpoint(self, server):
        status, data = _post(server, "/api/health", {"directory": REPO_ROOT})
        assert status == 200
        assert isinstance(data, dict)

    def test_connections_endpoint(self, server):
        status, data = _post(server, "/api/connection-test", {"directory": REPO_ROOT})
        assert status == 200
        assert isinstance(data, dict)


# ══════════════════════════════════════════════════════════════════════════
# 4. PM Dashboard APIs
# ══════════════════════════════════════════════════════════════════════════


class TestPMDashboardAPI:
    def test_risk_heatmap(self, server):
        status, data = _post(server, "/api/risk-heatmap", {"directory": REPO_ROOT})
        assert status == 200
        assert isinstance(data, dict)

    def test_module_cards(self, server):
        status, data = _post(server, "/api/module-cards", {"directory": REPO_ROOT})
        assert status == 200
        assert isinstance(data, dict)

    def test_confidence_meter(self, server):
        status, data = _post(server, "/api/confidence", {"directory": REPO_ROOT})
        assert status == 200
        assert isinstance(data, dict)

    def test_architecture_map(self, server):
        status, data = _post(server, "/api/architecture", {"directory": REPO_ROOT})
        assert status == 200
        assert isinstance(data, dict)


# ══════════════════════════════════════════════════════════════════════════
# 5. Chat API
# ══════════════════════════════════════════════════════════════════════════


class TestChatAPI:
    def test_chat_returns_reply(self, server):
        status, data = _post(server, "/api/chat", {"question": "hello"})
        assert status == 200
        assert "reply" in data

    def test_chat_empty_question(self, server):
        status, data = _post(server, "/api/chat", {"question": ""})
        assert status == 200
        assert "reply" in data


# ══════════════════════════════════════════════════════════════════════════
# 6. Error handling
# ══════════════════════════════════════════════════════════════════════════


class TestErrorHandling:
    def test_post_to_get_only_route(self, server):
        """POST to a GET-only endpoint should 404."""
        status, _ = _post(server, "/api/info", {})
        assert status == 404

    def test_get_to_post_only_route(self, server):
        """GET to a POST-only endpoint should 404."""
        status, _, _ = _get(server, "/api/smells")
        assert status == 404

    def test_invalid_json_body(self, server):
        """POST with invalid JSON should not crash the server."""
        host, port = server
        conn = HTTPConnection(host, port, timeout=10)
        conn.request(
            "POST", "/api/chat", body=b"not-json", headers={"Content-Type": "application/json", "Content-Length": "8"}
        )
        resp = conn.getresponse()
        resp.read()
        conn.close()
        # Server should still be alive
        status2, _, _ = _get(server, "/favicon.ico")
        assert status2 == 204
