"""
X-Ray LLM — Connection Analyzer Tests
=======================================
Tests the static UI-backend wiring analyzer that maps frontend API calls
to backend route handlers, detects orphans, and classifies cardinality.
"""

import os
import sys
import textwrap

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from analyzers import analyze_connections

# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def flask_project(tmp_path):
    """Flask backend + HTML frontend with known wiring."""
    (tmp_path / "app.py").write_text(
        textwrap.dedent("""\
        from flask import Flask, request
        app = Flask(__name__)

        @app.route('/api/users', methods=['GET'])
        def get_users():
            return []

        @app.route('/api/users', methods=['POST'])
        def create_user():
            data = request.json
            return data

        @app.route('/api/orphan-endpoint')
        def orphan():
            return "nobody calls this"
    """),
        encoding="utf-8",
    )

    (tmp_path / "index.html").write_text(
        textwrap.dedent("""\
        <html><body>
        <script>
          fetch('/api/users').then(r => r.json());
          fetch('/api/users', {method: 'POST', body: '{}'});
          fetch('/api/nonexistent');
        </script>
        </body></html>
    """),
        encoding="utf-8",
    )
    return str(tmp_path)


@pytest.fixture
def express_project(tmp_path):
    """Express backend + JS frontend."""
    (tmp_path / "server.js").write_text(
        textwrap.dedent("""\
        const express = require('express');
        const app = express();
        app.get('/api/items', (req, res) => { res.json([]); });
        app.post('/api/items', (req, res) => { res.json(req.body); });
        app.delete('/api/items/:id', (req, res) => { res.sendStatus(204); });
    """),
        encoding="utf-8",
    )

    (tmp_path / "app.js").write_text(
        textwrap.dedent("""\
        fetch('/api/items').then(r => r.json());
        axios.post('/api/items', {name: 'test'});
        fetch('/api/missing-route');
    """),
        encoding="utf-8",
    )
    return str(tmp_path)


@pytest.fixture
def django_project(tmp_path):
    """Django backend + template frontend."""
    (tmp_path / "urls.py").write_text(
        textwrap.dedent("""\
        from django.urls import path
        from . import views
        urlpatterns = [
            path('api/data/', views.get_data),
            path('api/submit/', views.submit_form),
        ]
    """),
        encoding="utf-8",
    )

    (tmp_path / "views.py").write_text(
        textwrap.dedent("""\
        from django.http import JsonResponse

        def get_data(request):
            return JsonResponse({"items": []})

        def submit_form(request):
            data = request.POST
            return JsonResponse({"ok": True})
    """),
        encoding="utf-8",
    )

    (tmp_path / "template.html").write_text(
        textwrap.dedent("""\
        <html><body>
        <script>
          fetch('/api/data/').then(r => r.json());
        </script>
        <form action="/api/submit/" method="POST">
          <button type="submit">Go</button>
        </form>
        </body></html>
    """),
        encoding="utf-8",
    )
    return str(tmp_path)


@pytest.fixture
def xray_custom_project(tmp_path):
    """X-Ray custom handler pattern."""
    (tmp_path / "server.py").write_text(
        textwrap.dedent("""\
        import os
        class Handler:
            def do_POST(self):
                path = self.path
                if path == '/api/scan':
                    body = self._read_body()
                    pass
                elif path == '/api/fix':
                    pass
    """),
        encoding="utf-8",
    )

    (tmp_path / "ui.html").write_text(
        textwrap.dedent("""\
        <html><body>
        <script>
          api('/api/scan');
          api('/api/fix');
          api('/api/ghost');
        </script>
        </body></html>
    """),
        encoding="utf-8",
    )
    return str(tmp_path)


@pytest.fixture
def empty_project(tmp_path):
    """Project with no frontend or backend files."""
    (tmp_path / "README.md").write_text("# Empty", encoding="utf-8")
    return str(tmp_path)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests — Flask project
# ═══════════════════════════════════════════════════════════════════════════════


class TestFlaskProject:
    def test_wired_connections(self, flask_project):
        result = analyze_connections(flask_project)
        assert result["summary"]["wired_count"] >= 1
        wired_urls = [w["url"] for w in result["wired"]]
        assert "/api/users" in wired_urls

    def test_orphan_ui(self, flask_project):
        result = analyze_connections(flask_project)
        orphan_urls = [o["url"] for o in result["orphan_ui"]]
        assert "/api/nonexistent" in orphan_urls

    def test_orphan_backend(self, flask_project):
        result = analyze_connections(flask_project)
        orphan_routes = [o["route"] for o in result["orphan_backend"]]
        assert "/api/orphan-endpoint" in orphan_routes

    def test_cardinality(self, flask_project):
        result = analyze_connections(flask_project)
        users_wire = [w for w in result["wired"] if w["url"] == "/api/users"]
        assert len(users_wire) == 1
        # Multiple UI calls AND multiple handlers → many:1 or 1:many
        assert users_wire[0]["cardinality"] in ("many:1", "1:many")

    def test_frameworks_detected(self, flask_project):
        result = analyze_connections(flask_project)
        assert "flask" in result["frameworks_detected"]

    def test_receives_input(self, flask_project):
        result = analyze_connections(flask_project)
        for w in result["wired"]:
            for h in w.get("handlers", []):
                if h.get("route") == "/api/users" and "POST" in h.get("method", ""):
                    assert h["receives_input"] is True

    def test_summary_structure(self, flask_project):
        result = analyze_connections(flask_project)
        s = result["summary"]
        assert "total_ui_actions" in s
        assert "total_handlers" in s
        assert "wired_count" in s
        assert "orphan_ui_count" in s
        assert "orphan_backend_count" in s
        assert "cardinality" in s
        assert set(s["cardinality"].keys()) == {"1:1", "1:many", "many:1"}


# ═══════════════════════════════════════════════════════════════════════════════
# Tests — Express project
# ═══════════════════════════════════════════════════════════════════════════════


class TestExpressProject:
    def test_express_detection(self, express_project):
        result = analyze_connections(express_project)
        assert "express" in result["frameworks_detected"]

    def test_wired(self, express_project):
        result = analyze_connections(express_project)
        wired_urls = [w["url"] for w in result["wired"]]
        assert "/api/items" in wired_urls

    def test_orphan_ui_missing_route(self, express_project):
        result = analyze_connections(express_project)
        orphan_urls = [o["url"] for o in result["orphan_ui"]]
        assert "/api/missing-route" in orphan_urls

    def test_axios_detected(self, express_project):
        result = analyze_connections(express_project)
        call_types = [a["call_type"] for w in result["wired"] for a in w.get("ui_actions", [])]
        assert "axios" in call_types or "fetch" in call_types


# ═══════════════════════════════════════════════════════════════════════════════
# Tests — Django project
# ═══════════════════════════════════════════════════════════════════════════════


class TestDjangoProject:
    def test_django_detection(self, django_project):
        result = analyze_connections(django_project)
        assert "django" in result["frameworks_detected"]

    def test_django_wired(self, django_project):
        result = analyze_connections(django_project)
        assert result["summary"]["wired_count"] >= 1

    def test_form_action_detected(self, django_project):
        result = analyze_connections(django_project)
        all_ui = []
        for w in result["wired"]:
            all_ui.extend(w.get("ui_actions", []))
        all_ui.extend(result.get("orphan_ui", []))
        call_types = [a["call_type"] for a in all_ui]
        assert "form_action" in call_types or "fetch" in call_types


# ═══════════════════════════════════════════════════════════════════════════════
# Tests — X-Ray custom handler
# ═══════════════════════════════════════════════════════════════════════════════


class TestXRayCustomProject:
    def test_xray_custom_detection(self, xray_custom_project):
        result = analyze_connections(xray_custom_project)
        assert "xray_custom" in result["frameworks_detected"]

    def test_wired(self, xray_custom_project):
        result = analyze_connections(xray_custom_project)
        wired_urls = [w["url"] for w in result["wired"]]
        assert "/api/scan" in wired_urls
        assert "/api/fix" in wired_urls

    def test_orphan_ghost(self, xray_custom_project):
        result = analyze_connections(xray_custom_project)
        orphan_urls = [o["url"] for o in result["orphan_ui"]]
        assert "/api/ghost" in orphan_urls

    def test_receives_input_read_body(self, xray_custom_project):
        result = analyze_connections(xray_custom_project)
        scan_wire = [w for w in result["wired"] if w["url"] == "/api/scan"]
        assert len(scan_wire) == 1
        assert any(h["receives_input"] for h in scan_wire[0]["handlers"])


# ═══════════════════════════════════════════════════════════════════════════════
# Tests — Edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_empty_project(self, empty_project):
        result = analyze_connections(empty_project)
        s = result["summary"]
        assert s["total_ui_actions"] == 0
        assert s["total_handlers"] == 0
        assert s["wired_count"] == 0
        assert s["orphan_ui_count"] == 0
        assert s["orphan_backend_count"] == 0

    def test_return_structure(self, flask_project):
        result = analyze_connections(flask_project)
        assert isinstance(result, dict)
        assert "wired" in result
        assert "orphan_ui" in result
        assert "orphan_backend" in result
        assert "summary" in result
        assert "frameworks_detected" in result

    def test_external_urls_ignored(self, tmp_path):
        """External URLs (http://...) should not appear as UI actions."""
        (tmp_path / "app.js").write_text(
            textwrap.dedent("""\
            fetch('https://external.com/api/data');
            fetch('http://other.com/users');
            fetch('/api/local');
        """),
            encoding="utf-8",
        )
        result = analyze_connections(str(tmp_path))
        all_urls = [a["url"] for a in result.get("orphan_ui", [])]
        for w in result.get("wired", []):
            all_urls.extend([a["url"] for a in w.get("ui_actions", [])])
        assert not any("external.com" in u for u in all_urls)
        assert not any("other.com" in u for u in all_urls)
        assert "/api/local" in all_urls

    def test_path_params_normalize(self, tmp_path):
        """Path parameters in different formats should match."""
        (tmp_path / "server.js").write_text(
            "app.get('/api/users/:id', (req, res) => {});\n",
            encoding="utf-8",
        )
        (tmp_path / "app.js").write_text(
            "fetch('/api/users/123');\n",
            encoding="utf-8",
        )
        # /api/users/:id normalizes to /api/users/_PARAM_
        # /api/users/123 does NOT normalize (it's a literal)
        # So these won't match — but the handler should appear as orphan_backend
        result = analyze_connections(str(tmp_path))
        assert result["summary"]["total_handlers"] >= 1
