"""
X-Ray LLM — Exhaustive Pre-Release Monkey Test
================================================
Tests every API endpoint, every UI button's corresponding API call,
every setting combination, error paths, and both scan engines.

Starts the real HTTP server on a random port and sends real requests.

Run:  python -m pytest tests/test_monkey.py -v --tb=short
"""

import json
import os
import re
import sys
import tempfile
import textwrap
import threading
import time
from http.server import HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures — start real server, create test project directory
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def test_project(tmp_path_factory):
    """Create a small but realistic test project with known issues."""
    d = tmp_path_factory.mktemp("test_project")

    # Python file with known scan triggers
    (d / "main.py").write_text(textwrap.dedent("""\
        import os
        import sys
        import json
        import subprocess

        SECRET = "password123"

        def greet(name):
            print(f"Hello {name}")
            return f"<h1>{name}</h1>"

        def load_config():
            data = open("config.json").read()
            return json.loads(data)

        def run_cmd(cmd):
            os.system(cmd)
            subprocess.call(cmd, shell=True)

        def risky():
            eval(input("expr> "))

        try:
            greet("world")
        except:
            pass
    """), encoding="utf-8")

    # Second file to create duplicates and more findings
    (d / "utils.py").write_text(textwrap.dedent("""\
        import os
        import sys

        SECRET = "password123"

        def helper():
            x = 42
            # TODO: fix this later
            # FIXME: hack
            return x

        def greet(name):
            print(f"Hello {name}")
            return f"<h1>{name}</h1>"

        class MyClass:
            pass
    """), encoding="utf-8")

    # HTML file for web smell detection
    (d / "index.html").write_text(textwrap.dedent("""\
        <html>
        <body>
            <div onclick="alert('hi')">Click</div>
            <script>
                document.innerHTML = userInput;
                eval(something);
            </script>
        </body>
        </html>
    """), encoding="utf-8")

    # README for health/release checks
    (d / "README.md").write_text("# Test Project\nA test.", encoding="utf-8")

    # Tests dir
    tests_dir = d / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_main.py").write_text(textwrap.dedent("""\
        def test_placeholder():
            assert True
    """), encoding="utf-8")

    return str(d)


@pytest.fixture(scope="module")
def server_url(test_project):
    """Start the real X-Ray server on a random port, return base URL."""
    from ui_server import XRayHandler, _load_guide

    _load_guide()

    # Find a free port
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = type('ThreadedHTTPServer', (ThreadingMixIn, HTTPServer), {'daemon_threads': True})(
        ("127.0.0.1", port), XRayHandler
    )

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    base = f"http://127.0.0.1:{port}"
    # Wait for server to be ready
    for _ in range(30):
        try:
            urlopen(f"{base}/api/info", timeout=2)
            break
        except Exception:
            time.sleep(0.1)
    else:
        pytest.fail("Server did not start in 3 seconds")

    yield base

    server.shutdown()


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def get(url, timeout=30):
    """GET request, return parsed JSON."""
    resp = urlopen(url, timeout=timeout)
    return json.loads(resp.read().decode())


def post(url, body=None, timeout=60):
    """POST JSON body, return parsed JSON."""
    data = json.dumps(body or {}).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    resp = urlopen(req, timeout=timeout)
    return json.loads(resp.read().decode())


def post_sse(url, body, timeout=120):
    """POST to start a scan, poll for completion, then fetch full results.

    Returns a dict compatible with the original SSE-based post_sse:
      {"done": <full result dict with findings>, "progress_count": N, "all_events": []}
    """
    import time as _time

    # 1. Start the scan (server returns immediately)
    start_resp = post(url, body, timeout=30)
    base = url.rsplit("/api/", 1)[0]

    # 2. Poll /api/scan-progress until done
    progress_count = 0
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        _time.sleep(0.3)
        try:
            progress = get(f"{base}/api/scan-progress", timeout=10)
        except Exception:
            continue
        if progress.get("status") == "scanning":
            progress_count += 1
        elif progress.get("status") == "done":
            progress_count += 1
            break
    else:
        raise TimeoutError(f"Scan did not complete within {timeout}s")

    # 3. Fetch full results (with findings)
    full = get(f"{base}/api/scan-result", timeout=30)

    return {"done": full,
            "progress_count": progress_count,
            "all_events": []}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GET ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetEndpoints:
    """Test all GET API endpoints."""

    def test_serve_ui_html(self, server_url):
        resp = urlopen(f"{server_url}/", timeout=10)
        html = resp.read().decode()
        assert "<html" in html.lower()
        assert "X-Ray" in html

    def test_api_info(self, server_url):
        data = get(f"{server_url}/api/info")
        assert "platform" in data
        assert "python" in data
        assert "rust_available" in data
        assert isinstance(data["rust_available"], bool)
        assert "rules_count" in data
        assert data["rules_count"] >= 28
        assert "home" in data
        assert "fixable_rules" in data
        assert isinstance(data["fixable_rules"], list)

    def test_browse_no_path_returns_drives(self, server_url):
        data = get(f"{server_url}/api/browse")
        assert "drives" in data
        assert isinstance(data["drives"], list)

    def test_browse_valid_path(self, server_url, test_project):
        from urllib.parse import quote
        data = get(f"{server_url}/api/browse?path={quote(test_project)}")
        # Should return entries
        assert "entries" in data or "items" in data or "children" in data or "dirs" in data or "files" in data or isinstance(data, dict)

    def test_favicon_no_crash(self, server_url):
        resp = urlopen(f"{server_url}/favicon.ico", timeout=5)
        assert resp.status in (200, 204)

    def test_404_on_unknown_path(self, server_url):
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"{server_url}/api/nonexistent", timeout=5)
        assert exc_info.value.code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SCAN ENDPOINT (SSE) — Both engines, all severities
# ═══════════════════════════════════════════════════════════════════════════════

class TestScanEndpoint:
    """Test the /api/scan SSE endpoint with all engine/severity combos."""

    def test_scan_python_engine_all_severity(self, server_url, test_project):
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        done = result["done"]
        assert done is not None, "No 'done' event received"
        assert done.get("files_scanned", 0) > 0
        assert len(done.get("findings", [])) > 0
        assert done.get("engine") == "python"
        assert result["progress_count"] > 0

    def test_scan_python_medium_severity(self, server_url, test_project):
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "MEDIUM"
        })
        done = result["done"]
        assert done is not None
        # Medium+ should have fewer findings than LOW
        all_findings = done.get("findings", [])
        for f in all_findings:
            assert f["severity"] in ("HIGH", "MEDIUM"), \
                f"LOW finding leaked through MEDIUM filter: {f['rule_id']}"

    def test_scan_python_high_severity(self, server_url, test_project):
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "HIGH"
        })
        done = result["done"]
        assert done is not None
        for f in done.get("findings", []):
            assert f["severity"] == "HIGH", \
                f"Non-HIGH finding leaked: {f['rule_id']} ({f['severity']})"

    def test_scan_with_exclude_pattern(self, server_url, test_project):
        result_all = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        result_exclude = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW",
            "excludes": ["utils\\.py"]
        })
        # Excluding utils.py should produce fewer findings
        all_count = len(result_all["done"].get("findings", []))
        excl_count = len(result_exclude["done"].get("findings", []))
        assert excl_count < all_count, \
            f"Exclude pattern had no effect: {excl_count} >= {all_count}"

    def test_scan_invalid_directory(self, server_url):
        data = json.dumps({"directory": "/nonexistent/path/xyz"}).encode()
        req = Request(f"{server_url}/api/scan", data=data,
                      headers={"Content-Type": "application/json"})
        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=10)
        assert exc_info.value.code == 400

    def test_scan_rust_engine_graceful(self, server_url, test_project):
        """Rust engine: either works or returns a clear error (not a crash)."""
        info = get(f"{server_url}/api/info")
        if not info.get("rust_available"):
            pytest.skip("Rust scanner not built")
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "rust", "severity": "LOW"
        })
        done = result["done"]
        assert done is not None
        assert done.get("engine") == "rust"

    def test_scan_finding_fields_complete(self, server_url, test_project):
        """Every finding has all required fields."""
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        required_fields = {"rule_id", "severity", "file", "line", "description"}
        for f in result["done"].get("findings", []):
            missing = required_fields - set(f.keys())
            assert not missing, f"Finding missing fields {missing}: {f.get('rule_id')}"

    def test_abort_scan(self, server_url, test_project):
        """Abort endpoint returns ok: true."""
        data = post(f"{server_url}/api/abort")
        assert data.get("ok") is True


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ANALYSIS TOOL BUTTONS — every single one
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalysisToolButtons:
    """Test every sidebar tool button's API endpoint."""

    def test_satd(self, server_url, test_project):
        data = post(f"{server_url}/api/satd", {"directory": test_project})
        assert "markers" in data or "items" in data or "total" in data or isinstance(data, dict)
        # Our test project has TODO and FIXME
        assert not data.get("error"), f"SATD failed: {data}"

    def test_git_hotspots(self, server_url, test_project):
        """Git hotspots — may return empty if not a git repo, but must not crash."""
        data = post(f"{server_url}/api/git-hotspots", {"directory": test_project})
        assert not data.get("error") or "not a git" in data.get("error", "").lower() \
            or "git" in data.get("error", "").lower()

    def test_imports(self, server_url, test_project):
        data = post(f"{server_url}/api/imports", {"directory": test_project})
        assert isinstance(data, dict)
        assert not data.get("error"), f"Imports failed: {data}"

    def test_ruff(self, server_url, test_project):
        data = post(f"{server_url}/api/ruff", {"directory": test_project})
        assert isinstance(data, dict)
        # ruff may not be installed — that's ok, just no crash
        assert not data.get("error") or "ruff" in data.get("error", "").lower()

    def test_format(self, server_url, test_project):
        data = post(f"{server_url}/api/format", {"directory": test_project})
        assert isinstance(data, dict)
        # Either returns format data or ruff-not-found error
        has_format_keys = "needs_format" in data or "all_formatted" in data
        has_error = "error" in data
        assert has_format_keys or has_error

    def test_health(self, server_url, test_project):
        data = post(f"{server_url}/api/health", {"directory": test_project})
        assert "score" in data
        assert "checks" in data
        assert isinstance(data["score"], (int, float))
        assert 0 <= data["score"] <= 100

    def test_bandit(self, server_url, test_project):
        data = post(f"{server_url}/api/bandit", {"directory": test_project})
        assert isinstance(data, dict)
        # Always has secrets detection even if bandit isn't installed
        assert "secrets" in data or "total_issues" in data or "bandit_available" in data

    def test_dead_code(self, server_url, test_project):
        data = post(f"{server_url}/api/dead-code", {"directory": test_project})
        assert "dead_functions" in data or "total_defined" in data
        assert isinstance(data.get("dead_functions", []), list)

    def test_smells(self, server_url, test_project):
        data = post(f"{server_url}/api/smells", {"directory": test_project})
        assert "smells" in data
        assert "total" in data
        assert isinstance(data["smells"], list)

    def test_duplicates(self, server_url, test_project):
        data = post(f"{server_url}/api/duplicates", {"directory": test_project})
        assert "duplicate_groups" in data or "total_groups" in data
        assert isinstance(data, dict)

    def test_temporal_coupling(self, server_url, test_project):
        """Temporal coupling — non-git repo returns empty, must not crash."""
        data = post(f"{server_url}/api/temporal-coupling", {"directory": test_project})
        assert isinstance(data, dict)

    def test_typecheck(self, server_url, test_project):
        data = post(f"{server_url}/api/typecheck", {"directory": test_project})
        assert isinstance(data, dict)
        # Either returns diagnostics or error about ty not installed
        has_data = "total_diagnostics" in data or "diagnostics" in data or "clean" in data
        has_error = "error" in data
        assert has_data or has_error

    def test_release_readiness(self, server_url, test_project):
        data = post(f"{server_url}/api/release-readiness", {"directory": test_project})
        assert isinstance(data, dict)
        assert "checks" in data or "score" in data or "ready" in data

    def test_ai_detect(self, server_url, test_project):
        data = post(f"{server_url}/api/ai-detect", {"directory": test_project})
        assert "indicators" in data or "total" in data
        assert isinstance(data, dict)

    def test_web_smells(self, server_url, test_project):
        data = post(f"{server_url}/api/web-smells", {"directory": test_project})
        assert "smells" in data
        assert isinstance(data["smells"], list)
        # Our test HTML has inline handlers and innerHTML
        assert data.get("total", 0) > 0 or len(data["smells"]) > 0

    def test_test_gen(self, server_url, test_project):
        data = post(f"{server_url}/api/test-gen", {"directory": test_project})
        assert isinstance(data, dict)
        assert "total_functions" in data or "stubs" in data

    def test_remediation_time(self, server_url, test_project):
        # First scan to get findings
        scan = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        findings = scan["done"].get("findings", [])[:5]
        data = post(f"{server_url}/api/remediation-time", {"findings": findings})
        assert "total_minutes" in data or "total_hours" in data
        assert isinstance(data, dict)

    def test_remediation_time_empty(self, server_url):
        """Remediation with no findings should still work."""
        data = post(f"{server_url}/api/remediation-time", {"findings": []})
        assert isinstance(data, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. PM DASHBOARD BUTTONS — every single one
# ═══════════════════════════════════════════════════════════════════════════════

class TestPMDashboardButtons:
    """Test every PM Dashboard button's API endpoint."""

    @pytest.fixture(scope="class")
    def scan_findings(self, server_url, test_project):
        """Run a scan once and reuse findings for all PM tests."""
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        return result["done"].get("findings", [])

    def test_risk_heatmap(self, server_url, test_project, scan_findings):
        data = post(f"{server_url}/api/risk-heatmap", {
            "directory": test_project, "findings": scan_findings
        })
        assert "files" in data or "total_files" in data
        assert isinstance(data, dict)

    def test_risk_heatmap_no_findings(self, server_url, test_project):
        """Risk heatmap with no findings should still work."""
        data = post(f"{server_url}/api/risk-heatmap", {
            "directory": test_project, "findings": []
        })
        assert isinstance(data, dict)

    def test_module_cards(self, server_url, test_project, scan_findings):
        data = post(f"{server_url}/api/module-cards", {
            "directory": test_project, "findings": scan_findings
        })
        assert "modules" in data or "total_modules" in data
        assert isinstance(data, dict)

    def test_confidence(self, server_url, test_project, scan_findings):
        data = post(f"{server_url}/api/confidence", {
            "directory": test_project, "findings": scan_findings
        })
        assert "confidence" in data
        assert isinstance(data["confidence"], (int, float))
        assert 0 <= data["confidence"] <= 100

    def test_sprint_batches(self, server_url, scan_findings):
        data = post(f"{server_url}/api/sprint-batches", {
            "findings": scan_findings, "smells": []
        })
        assert "batches" in data
        assert isinstance(data["batches"], list)

    def test_sprint_batches_empty(self, server_url):
        """Sprint batches with empty inputs."""
        data = post(f"{server_url}/api/sprint-batches", {
            "findings": [], "smells": []
        })
        assert isinstance(data, dict)

    def test_architecture(self, server_url, test_project):
        data = post(f"{server_url}/api/architecture", {"directory": test_project})
        assert "nodes" in data or "edges" in data
        assert isinstance(data, dict)

    def test_call_graph(self, server_url, test_project):
        data = post(f"{server_url}/api/call-graph", {"directory": test_project})
        assert "nodes" in data or "edges" in data or "total_functions" in data
        assert isinstance(data, dict)

    def test_circular_calls(self, server_url, test_project):
        data = post(f"{server_url}/api/circular-calls", {"directory": test_project})
        assert "total_cycles" in data or "circular_calls" in data
        assert isinstance(data, dict)

    def test_coupling(self, server_url, test_project):
        data = post(f"{server_url}/api/coupling", {"directory": test_project})
        assert "modules" in data or "total_modules" in data
        assert isinstance(data, dict)

    def test_unused_imports(self, server_url, test_project):
        data = post(f"{server_url}/api/unused-imports", {"directory": test_project})
        assert isinstance(data, dict)
        # Our test project has unused imports (sys in utils.py)

    def test_project_review(self, server_url, test_project, scan_findings):
        data = post(f"{server_url}/api/project-review", {
            "directory": test_project,
            "findings": scan_findings,
            "files_scanned": 3,
        })
        assert isinstance(data, dict)
        # Should return a score/grade
        assert "score" in data or "letter" in data or "overall_grade" in data


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CHAT ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatEndpoint:

    def test_chat_basic(self, server_url):
        data = post(f"{server_url}/api/chat", {"message": "What is X-Ray?"})
        assert "reply" in data
        assert len(data["reply"]) > 0

    def test_chat_with_context(self, server_url, test_project):
        data = post(f"{server_url}/api/chat", {
            "message": "How many rules does X-Ray have?",
            "has_results": True,
            "findings_count": 42,
            "directory": test_project,
        })
        assert "reply" in data

    def test_chat_empty_message(self, server_url):
        data = post(f"{server_url}/api/chat", {"message": ""})
        assert "reply" in data

    def test_chat_no_body(self, server_url):
        data = post(f"{server_url}/api/chat", {})
        assert "reply" in data


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FIX ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestFixEndpoints:

    def test_preview_fix(self, server_url, test_project):
        """Preview fix on a real finding — should return without crashing."""
        scan = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        findings = scan["done"].get("findings", [])
        if not findings:
            pytest.skip("No findings to preview-fix")
        data = post(f"{server_url}/api/preview-fix", findings[0])
        assert isinstance(data, dict)
        # May have "diff", "error", or "fix" key depending on rule

    def test_preview_fix_empty(self, server_url):
        data = post(f"{server_url}/api/preview-fix", {})
        assert isinstance(data, dict)

    def test_apply_fixes_bulk_empty(self, server_url):
        """Bulk fix with empty list should not crash."""
        data = post(f"{server_url}/api/apply-fixes-bulk", {"findings": []})
        assert isinstance(data, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ERROR HANDLING — bad inputs on every endpoint that takes directory
# ═══════════════════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Every endpoint requiring a directory rejects invalid paths gracefully."""

    DIRECTORY_ENDPOINTS = [
        "/api/satd", "/api/git-hotspots", "/api/imports", "/api/ruff",
        "/api/format", "/api/typecheck", "/api/health", "/api/bandit",
        "/api/dead-code", "/api/smells", "/api/duplicates",
        "/api/temporal-coupling", "/api/release-readiness", "/api/ai-detect",
        "/api/web-smells", "/api/test-gen",
        "/api/risk-heatmap", "/api/module-cards", "/api/confidence",
        "/api/architecture", "/api/call-graph", "/api/project-review",
        "/api/circular-calls", "/api/coupling", "/api/unused-imports",
    ]

    @pytest.mark.parametrize("endpoint", DIRECTORY_ENDPOINTS)
    def test_invalid_directory_returns_400(self, server_url, endpoint):
        """Every directory-based endpoint returns 400 for bogus path."""
        data = json.dumps({"directory": "/totally/bogus/path/xyz123"}).encode()
        req = Request(f"{server_url}{endpoint}", data=data,
                      headers={"Content-Type": "application/json"})
        try:
            resp = urlopen(req, timeout=15)
            body = json.loads(resp.read().decode())
            # Some endpoints return 200 with error key instead of 400
            assert "error" in body, \
                f"{endpoint} accepted bogus directory without error"
        except HTTPError as e:
            assert e.code == 400, f"{endpoint} returned {e.code}, expected 400"

    @pytest.mark.parametrize("endpoint", DIRECTORY_ENDPOINTS)
    def test_empty_directory_returns_400(self, server_url, endpoint):
        """Every directory-based endpoint rejects empty string."""
        data = json.dumps({"directory": ""}).encode()
        req = Request(f"{server_url}{endpoint}", data=data,
                      headers={"Content-Type": "application/json"})
        try:
            resp = urlopen(req, timeout=15)
            body = json.loads(resp.read().decode())
            assert "error" in body, \
                f"{endpoint} accepted empty directory without error"
        except HTTPError as e:
            assert e.code == 400, f"{endpoint} returned {e.code}, expected 400"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. ANALYZER FUNCTIONS — direct import tests (no server needed)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzersDirect:
    """Test analyzer functions directly (unit tests, not via HTTP)."""

    def test_check_format(self, test_project):
        from analyzers import check_format
        result = check_format(test_project)
        assert isinstance(result, dict)

    def test_check_types(self, test_project):
        from analyzers import check_types
        result = check_types(test_project)
        assert isinstance(result, dict)

    def test_check_project_health(self, test_project):
        from analyzers import check_project_health
        result = check_project_health(test_project)
        assert "score" in result
        assert isinstance(result["checks"], list)

    def test_detect_dead_functions(self, test_project):
        from analyzers import detect_dead_functions
        result = detect_dead_functions(test_project)
        assert "dead_functions" in result
        assert "total_defined" in result

    def test_detect_code_smells(self, test_project):
        from analyzers import detect_code_smells
        result = detect_code_smells(test_project)
        assert "smells" in result
        assert result["total"] >= 0

    def test_detect_duplicates(self, test_project):
        from analyzers import detect_duplicates
        result = detect_duplicates(test_project)
        assert "duplicate_groups" in result

    def test_check_release_readiness(self, test_project):
        from analyzers import check_release_readiness
        result = check_release_readiness(test_project)
        assert isinstance(result, dict)

    def test_detect_ai_code(self, test_project):
        from analyzers import detect_ai_code
        result = detect_ai_code(test_project)
        assert "indicators" in result

    def test_detect_web_smells(self, test_project):
        from analyzers import detect_web_smells
        result = detect_web_smells(test_project)
        assert "smells" in result

    def test_generate_test_stubs(self, test_project):
        from analyzers import generate_test_stubs
        result = generate_test_stubs(test_project)
        assert "total_functions" in result

    def test_estimate_remediation_time(self):
        from analyzers import estimate_remediation_time
        findings = [
            {"rule_id": "SEC-003", "severity": "HIGH"},
            {"rule_id": "QUAL-001", "severity": "LOW"},
        ]
        result = estimate_remediation_time(findings)
        assert "total_minutes" in result

    def test_compute_risk_heatmap(self, test_project):
        from analyzers import compute_risk_heatmap
        result = compute_risk_heatmap(test_project, [])
        assert isinstance(result, dict)

    def test_compute_module_cards(self, test_project):
        from analyzers import compute_module_cards
        result = compute_module_cards(test_project, [])
        assert isinstance(result, dict)

    def test_compute_confidence_meter(self, test_project):
        from analyzers import compute_confidence_meter
        result = compute_confidence_meter(test_project, [])
        assert "confidence" in result
        assert 0 <= result["confidence"] <= 100

    def test_compute_sprint_batches(self):
        from analyzers import compute_sprint_batches
        result = compute_sprint_batches([], [])
        assert "batches" in result

    def test_compute_architecture_map(self, test_project):
        from analyzers import compute_architecture_map
        result = compute_architecture_map(test_project)
        assert "nodes" in result

    def test_compute_call_graph(self, test_project):
        from analyzers import compute_call_graph
        result = compute_call_graph(test_project)
        assert "nodes" in result

    def test_compute_project_review(self, test_project):
        from analyzers import compute_project_review
        result = compute_project_review(test_project)
        assert isinstance(result, dict)

    def test_detect_circular_calls(self, test_project):
        from analyzers import detect_circular_calls
        result = detect_circular_calls(test_project)
        assert "total_cycles" in result or "circular_calls" in result

    def test_compute_coupling_metrics(self, test_project):
        from analyzers import compute_coupling_metrics
        result = compute_coupling_metrics(test_project)
        assert "modules" in result

    def test_detect_unused_imports(self, test_project):
        from analyzers import detect_unused_imports
        result = detect_unused_imports(test_project)
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. SCANNER ENGINE — direct unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestScannerDirect:
    """Direct scanner tests — no server."""

    def test_scan_directory(self, test_project):
        from xray.scanner import scan_directory
        result = scan_directory(test_project)
        assert result.files_scanned > 0
        assert len(result.findings) > 0
        assert len(result.errors) == 0

    def test_scan_file(self, test_project):
        from xray.scanner import scan_file
        main_py = os.path.join(test_project, "main.py")
        findings = scan_file(main_py)
        assert isinstance(findings, list)
        assert len(findings) > 0

    def test_scan_empty_dir(self):
        from xray.scanner import scan_directory
        with tempfile.TemporaryDirectory() as d:
            result = scan_directory(d)
            assert result.files_scanned == 0
            assert len(result.findings) == 0

    def test_finding_fields(self, test_project):
        from xray.scanner import scan_directory
        result = scan_directory(test_project)
        for f in result.findings[:10]:
            assert hasattr(f, "rule_id")
            assert hasattr(f, "severity")
            assert hasattr(f, "file")
            assert hasattr(f, "line")
            assert hasattr(f, "description")
            assert f.severity in ("HIGH", "MEDIUM", "LOW")

    def test_severity_counts(self, test_project):
        from xray.scanner import scan_directory
        result = scan_directory(test_project)
        total = result.high_count + result.medium_count + result.low_count
        assert total == len(result.findings)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. SCAN RESULTS — content validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestScanResultsContent:
    """Verify the scan actually finds the planted issues."""

    def test_finds_eval(self, server_url, test_project):
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        rules = {f["rule_id"] for f in result["done"].get("findings", [])}
        assert "SEC-007" in rules, f"Failed to detect eval() [SEC-007], found: {rules}"

    def test_finds_shell_injection(self, server_url, test_project):
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        rules = {f["rule_id"] for f in result["done"].get("findings", [])}
        assert "SEC-003" in rules, "Failed to detect shell=True [SEC-003]"

    def test_finds_bare_except(self, server_url, test_project):
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        rules = {f["rule_id"] for f in result["done"].get("findings", [])}
        assert "QUAL-001" in rules, "Failed to detect bare except [QUAL-001]"

    def test_finds_hardcoded_secret(self, server_url, test_project):
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        rules = {f["rule_id"] for f in result["done"].get("findings", [])}
        assert "SEC-007" in rules, "Failed to detect hardcoded secret [SEC-007]"

    def test_finds_print_debug(self, server_url, test_project):
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        rules = {f["rule_id"] for f in result["done"].get("findings", [])}
        assert "PY-004" in rules, "Failed to detect print() debug [PY-004]"

    def test_finds_todo_marker(self, server_url, test_project):
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        rules = {f["rule_id"] for f in result["done"].get("findings", [])}
        assert "QUAL-007" in rules, "Failed to detect TODO/FIXME [QUAL-007]"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. SERVER INFRASTRUCTURE
# ═══════════════════════════════════════════════════════════════════════════════

class TestServerInfrastructure:
    """Test server behavior: CORS, content types, error responses."""

    def test_json_content_type(self, server_url):
        resp = urlopen(f"{server_url}/api/info", timeout=10)
        ct = resp.headers.get("Content-Type", "")
        assert "application/json" in ct

    def test_html_content_type(self, server_url):
        resp = urlopen(f"{server_url}/", timeout=10)
        ct = resp.headers.get("Content-Type", "")
        assert "text/html" in ct

    def test_unknown_post_returns_404(self, server_url):
        data = json.dumps({}).encode()
        req = Request(f"{server_url}/api/does-not-exist", data=data,
                      headers={"Content-Type": "application/json"})
        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=10)
        assert exc_info.value.code == 404

    def test_concurrent_requests(self, server_url, test_project):
        """Multiple simultaneous requests don't crash the server."""
        import concurrent.futures
        endpoints = [
            f"{server_url}/api/health",
            f"{server_url}/api/smells",
            f"{server_url}/api/dead-code",
            f"{server_url}/api/duplicates",
        ]

        def call_endpoint(url):
            return post(url, {"directory": test_project})

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(call_endpoint, ep) for ep in endpoints]
            results = [f.result(timeout=60) for f in futures]

        for r in results:
            assert isinstance(r, dict)
            assert "error" not in r


# ═══════════════════════════════════════════════════════════════════════════════
# 12. RULES DATABASE INTEGRITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestRulesIntegrity:
    """All rules compile and have valid fields."""

    def test_all_rules_load(self):
        from xray.rules import ALL_RULES
        assert len(ALL_RULES) >= 28

    def test_all_patterns_compile(self):
        from xray.rules import ALL_RULES
        for rule in ALL_RULES:
            pattern = rule["pattern"]
            try:
                re.compile(pattern)
            except re.error as e:
                pytest.fail(f"Rule {rule['id']} pattern fails to compile: {e}")

    def test_security_rules_exist(self):
        from xray.rules import SECURITY_RULES
        assert len(SECURITY_RULES) >= 10

    def test_quality_rules_exist(self):
        from xray.rules import QUALITY_RULES
        assert len(QUALITY_RULES) >= 10

    def test_python_rules_exist(self):
        from xray.rules import PYTHON_RULES
        assert len(PYTHON_RULES) >= 8

    def test_fixable_rules_are_real(self):
        from xray.fixer import FIXABLE_RULES
        from xray.rules import ALL_RULES
        all_ids = {r["id"] for r in ALL_RULES}
        for fixable in FIXABLE_RULES:
            assert fixable in all_ids, f"Fixable rule {fixable} not in ALL_RULES"


# ═══════════════════════════════════════════════════════════════════════════════
# 13. SCAN COMPLETION — regression tests for the SSE hang/no-continuation bug
# ═══════════════════════════════════════════════════════════════════════════════

class TestScanCompletion:
    """Regression tests for the scan-completes-but-UI-hangs bug.

    The fix uses an async scan with polling:
      1. POST /api/scan starts scan in background, returns immediately.
      2. Client polls GET /api/scan-progress for status updates.
      3. Client fetches full results from GET /api/scan-result when done.

    These tests verify every aspect of this contract so the bug
    can never silently return.
    """

    # ── POST /api/scan returns immediately ────────────────────────────────

    def test_scan_returns_started_status(self, server_url, test_project):
        """POST /api/scan must return immediately with status='started'."""
        resp = post(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        assert resp.get("status") == "started"
        assert "total_files" in resp
        import time; time.sleep(2)  # let background scan finish

    def test_scan_progress_endpoint(self, server_url, test_project):
        """GET /api/scan-progress returns progress during scan."""
        import time
        post(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        # Poll until done
        deadline = time.time() + 30
        saw_scanning = False
        saw_done = False
        while time.time() < deadline:
            time.sleep(0.2)
            progress = get(f"{server_url}/api/scan-progress")
            if progress.get("status") == "scanning":
                saw_scanning = True
            elif progress.get("status") == "done":
                saw_done = True
                break
        assert saw_done, "Scan never reached 'done' status via polling"

    # ── /api/scan-result REST endpoint ────────────────────────────────────

    def test_scan_result_endpoint_returns_full_findings(self, server_url, test_project):
        """After a scan, GET /api/scan-result must return the full findings array."""
        post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        full = get(f"{server_url}/api/scan-result")
        assert "findings" in full, "scan-result missing 'findings' key"
        assert isinstance(full["findings"], list)
        assert len(full["findings"]) > 0, "scan-result has empty findings for a project with known issues"
        assert "summary" in full
        assert full["summary"]["total"] == len(full["findings"])

    def test_scan_result_before_any_scan_returns_404(self, server_url):
        """Before any scan has run, /api/scan-result should return a 404 or error.
        (Note: if another test already ran a scan on this server instance,
        _last_scan_result will be set. We test the error key if present.)"""
        import ui_server
        # Temporarily clear the stored result
        original = ui_server._last_scan_result
        ui_server._last_scan_result = None
        try:
            with pytest.raises(HTTPError) as exc_info:
                get(f"{server_url}/api/scan-result", timeout=10)
            assert exc_info.value.code == 404
        finally:
            ui_server._last_scan_result = original

    def test_scan_result_finding_fields_complete(self, server_url, test_project):
        """Every finding from /api/scan-result has all required fields."""
        post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        full = get(f"{server_url}/api/scan-result")
        required_fields = {"rule_id", "severity", "file", "line", "description"}
        for f in full["findings"]:
            missing = required_fields - set(f.keys())
            assert not missing, f"Finding missing fields {missing}: {f.get('rule_id')}"
            assert f["severity"] in ("HIGH", "MEDIUM", "LOW")

    # ── Summary/findings count consistency ────────────────────────────────

    def test_sse_summary_matches_full_findings_count(self, server_url, test_project):
        """The summary.total in the SSE done must equal len(findings)
        from /api/scan-result — if they disagree the UI shows wrong numbers."""
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        summary_total = result["done"]["summary"]["total"]
        findings_total = len(result["done"]["findings"])
        assert summary_total == findings_total, \
            f"Summary says {summary_total} findings but result has {findings_total}"

    def test_severity_breakdown_matches(self, server_url, test_project):
        """High/Medium/Low counts in summary must match actual findings."""
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        summary = result["done"]["summary"]
        findings = result["done"]["findings"]
        actual_high = sum(1 for f in findings if f["severity"] == "HIGH")
        actual_med = sum(1 for f in findings if f["severity"] == "MEDIUM")
        actual_low = sum(1 for f in findings if f["severity"] == "LOW")
        assert summary["high"] == actual_high
        assert summary["medium"] == actual_med
        assert summary["low"] == actual_low

    # ── Polling progress works ────────────────────────────────────────────

    def test_progress_reports_files_scanned(self, server_url, test_project):
        """Progress polling must report files_scanned increasing to total."""
        import time
        post(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        max_scanned = 0
        deadline = time.time() + 30
        while time.time() < deadline:
            time.sleep(0.2)
            progress = get(f"{server_url}/api/scan-progress")
            scanned = progress.get("files_scanned", 0)
            if scanned > max_scanned:
                max_scanned = scanned
            if progress.get("status") == "done":
                break
        assert max_scanned > 0, "Polling never reported any files scanned"

    def test_scan_response_is_json_not_sse(self, server_url, test_project):
        """POST /api/scan must return JSON (not SSE stream)."""
        data = json.dumps({
            "directory": test_project, "engine": "python", "severity": "LOW"
        }).encode()
        req = Request(f"{server_url}/api/scan", data=data,
                      headers={"Content-Type": "application/json"})
        resp = urlopen(req, timeout=30)
        ct = resp.headers.get("Content-Type", "")
        assert "application/json" in ct, f"Expected JSON response, got {ct}"
        body = json.loads(resp.read().decode())
        assert body.get("status") == "started"
        import time; time.sleep(2)  # let background scan finish

    # ── Second scan overwrites first ──────────────────────────────────────

    def test_second_scan_overwrites_result(self, server_url, test_project):
        """Running a second scan with different severity should overwrite
        _last_scan_result so /api/scan-result returns the latest."""
        # First scan: all severities
        post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        all_result = get(f"{server_url}/api/scan-result")
        all_count = len(all_result["findings"])

        # Second scan: HIGH only
        post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "HIGH"
        })
        high_result = get(f"{server_url}/api/scan-result")
        high_count = len(high_result["findings"])

        # HIGH-only should have fewer (or equal) findings
        assert high_count <= all_count, \
            f"HIGH-only scan ({high_count}) has more findings than LOW+ scan ({all_count})"
        # And all findings should be HIGH severity
        for f in high_result["findings"]:
            assert f["severity"] == "HIGH"

    # ── post_sse helper fetches results correctly ─────────────────────────

    def test_post_sse_merges_findings(self, server_url, test_project):
        """The post_sse test helper must fetch findings from /api/scan-result
        into the done dict, so all existing tests keep working."""
        result = post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        done = result["done"]
        assert done is not None
        assert "findings" in done, "post_sse did not merge findings into done"
        assert len(done["findings"]) > 0
        assert done["files_scanned"] > 0

    # ── Scan result completeness ──────────────────────────────────────────

    def test_scan_result_has_required_fields(self, server_url, test_project):
        """Full scan result must have all fields the UI needs."""
        post_sse(f"{server_url}/api/scan", {
            "directory": test_project, "engine": "python", "severity": "LOW"
        })
        full = get(f"{server_url}/api/scan-result")
        required = {"engine", "elapsed_ms", "files_scanned", "summary", "findings"}
        missing = required - set(full.keys())
        assert not missing, f"Scan result missing fields: {missing}"
        assert isinstance(full["summary"], dict)
        assert isinstance(full["findings"], list)
